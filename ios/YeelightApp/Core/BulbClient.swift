import Foundation
import Network

/// Koneksi TCP persisten ke satu lampu (setara YeelightClient di client.py).
///
/// Satu koneksi dipakai ulang untuk semua perintah karena firmware hanya
/// mengizinkan empat koneksi TCP simultan.
actor BulbClient {
    let host: String
    let port: UInt16

    private let queue = DispatchQueue(label: "yeelight.bulb.socket")
    private var connection: NWConnection?
    private var ready = false
    private var readyWaiter: CheckedContinuation<Void, Error>?
    private var pending: [Int: CheckedContinuation<Any, Error>] = [:]
    private var buffer = Data()
    private var nextID = 1
    private var disconnectHandler: (@Sendable (String) -> Void)?
    private var closedByUser = false

    init(host: String, port: UInt16 = Proto.controlPort) {
        self.host = host
        self.port = port
    }

    func setDisconnectHandler(_ handler: @escaping @Sendable (String) -> Void) {
        disconnectHandler = handler
    }

    // MARK: - Koneksi

    func connect() async throws {
        if ready, let connection, connection.state == .ready { return }
        teardown()
        closedByUser = false

        let endpoint = NWEndpoint.hostPort(
            host: NWEndpoint.Host(host),
            port: NWEndpoint.Port(rawValue: port)!
        )
        let conn = NWConnection(to: endpoint, using: .tcp)
        connection = conn

        try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
            readyWaiter = continuation
            conn.stateUpdateHandler = { [weak self] state in
                Task { await self?.handleState(state) }
            }
            conn.start(queue: queue)
        }
        Task { [weak self] in
            try? await Task.sleep(nanoseconds: 4_000_000_000)
            await self?.failConnectIfPending(conn)
        }
        receiveNext()
    }

    /// Jangan sampai `connect()` menggantung kalau iOS menahan koneksi di state `.waiting`.
    private func failConnectIfPending(_ target: NWConnection) {
        guard connection === target, let waiter = readyWaiter else { return }
        readyWaiter = nil
        ready = false
        connection?.stateUpdateHandler = nil
        connection?.cancel()
        connection = nil
        waiter.resume(throwing: BulbError.timeout(method: "connect"))
    }

    func close() {
        closedByUser = true
        teardown()
    }

    private func teardown() {
        ready = false
        connection?.stateUpdateHandler = nil
        connection?.cancel()
        connection = nil
        failAll(BulbError.transport("koneksi ditutup"))
        if let waiter = readyWaiter {
            readyWaiter = nil
            waiter.resume(throwing: BulbError.transport("koneksi ditutup"))
        }
    }

    private func handleState(_ state: NWConnection.State) {
        switch state {
        case .ready:
            ready = true
            if let waiter = readyWaiter {
                readyWaiter = nil
                waiter.resume()
            }
        case let .failed(error):
            let mapped = Self.map(error)
            ready = false
            if let waiter = readyWaiter {
                readyWaiter = nil
                waiter.resume(throwing: mapped)
            }
            failAll(mapped)
            if !closedByUser {
                disconnectHandler?(mapped.localizedDescription)
            }
        case let .waiting(error):
            // "Connection refused" biasanya muncul sebagai .waiting, bukan .failed.
            if case let .posix(code) = error, code == .ECONNREFUSED {
                let mapped = BulbError.lanControlDisabled
                ready = false
                if let waiter = readyWaiter {
                    readyWaiter = nil
                    waiter.resume(throwing: mapped)
                }
                failAll(mapped)
                connection?.cancel()
                if !closedByUser {
                    disconnectHandler?(mapped.localizedDescription)
                }
            }
        case .cancelled:
            ready = false
            if let waiter = readyWaiter {
                readyWaiter = nil
                waiter.resume(throwing: BulbError.transport("koneksi dibatalkan"))
            }
        default:
            break
        }
    }

    private static func map(_ error: NWError) -> BulbError {
        if case let .posix(code) = error, code == .ECONNREFUSED {
            return .lanControlDisabled
        }
        return .transport(error.localizedDescription)
    }

    // MARK: - Menerima data

    private func receiveNext() {
        guard let connection else { return }
        connection.receive(minimumIncompleteLength: 1, maximumLength: 65536) { [weak self] data, _, isComplete, error in
            Task { await self?.handleReceive(data: data, isComplete: isComplete, error: error) }
        }
    }

    private func handleReceive(data: Data?, isComplete: Bool, error: NWError?) {
        if let data, !data.isEmpty {
            buffer.append(data)
            while let newline = buffer.firstIndex(of: 0x0A) {
                let lineData = buffer[buffer.startIndex..<newline]
                buffer.removeSubrange(buffer.startIndex...newline)
                let text = String(decoding: lineData, as: UTF8.self)
                    .trimmingCharacters(in: .whitespacesAndNewlines)
                if !text.isEmpty {
                    handleLine(text)
                }
            }
        }

        if let error {
            let mapped = Self.map(error)
            ready = false
            failAll(mapped)
            if !closedByUser {
                disconnectHandler?(mapped.localizedDescription)
            }
            return
        }
        if isComplete {
            ready = false
            failAll(BulbError.transport("lampu menutup koneksi"))
            if !closedByUser {
                disconnectHandler?("lampu menutup koneksi")
            }
            return
        }
        receiveNext()
    }

    private func handleLine(_ text: String) {
        guard
            let data = text.data(using: .utf8),
            let object = try? JSONSerialization.jsonObject(with: data),
            let message = object as? [String: Any]
        else {
            return
        }

        // Notifikasi "props" tidak punya id; aplikasi ini membaca state lewat polling.
        guard let rawID = message["id"] else { return }
        let id = (rawID as? Int) ?? (rawID as? NSNumber)?.intValue ?? -1
        guard let continuation = pending.removeValue(forKey: id) else { return }

        if let errorObject = message["error"] as? [String: Any] {
            let code = (errorObject["code"] as? Int) ?? -1
            let messageText = (errorObject["message"] as? String) ?? "unknown"
            continuation.resume(throwing: BulbError.command(code: code, message: messageText, method: nil))
            return
        }
        continuation.resume(returning: message["result"] ?? [Any]())
    }

    private func failAll(_ error: BulbError) {
        let waiters = pending
        pending.removeAll()
        for continuation in waiters.values {
            continuation.resume(throwing: error)
        }
    }

    // MARK: - Perintah

    func send(_ method: String, _ params: [Any] = [], timeout: TimeInterval = 5) async throws -> Any {
        if !ready {
            try await connect()
        }
        guard let connection else {
            throw BulbError.transport("belum terhubung")
        }
        let id = nextID
        nextID += 1
        let payload = try Proto.command(id: id, method: method, params: params)

        let result: Any = try await withCheckedThrowingContinuation { continuation in
            pending[id] = continuation

            Task { [weak self] in
                try? await Task.sleep(nanoseconds: UInt64(max(0.2, timeout) * 1_000_000_000))
                await self?.timeoutRequest(id: id, method: method)
            }

            connection.send(content: payload, completion: .contentProcessed { [weak self] error in
                guard let error else { return }
                Task {
                    await self?.failRequest(
                        id: id,
                        error: BulbError.transport(error.localizedDescription)
                    )
                }
            })
        }
        return result
    }

    private func timeoutRequest(id: Int, method: String) {
        guard let continuation = pending.removeValue(forKey: id) else { return }
        continuation.resume(throwing: BulbError.timeout(method: method))
    }

    private func failRequest(id: Int, error: BulbError) {
        guard let continuation = pending.removeValue(forKey: id) else { return }
        continuation.resume(throwing: error)
    }

    // MARK: - API tingkat tinggi

    func getProps(_ keys: [String] = Proto.statusProps + ["model"]) async throws -> [String: Any] {
        let result = try await send("get_prop", keys)
        guard let values = result as? [Any] else {
            throw BulbError.malformed("get_prop bukan array")
        }
        var props: [String: Any] = [:]
        for (index, key) in keys.enumerated() {
            props[key] = index < values.count ? values[index] : ""
        }
        return props
    }

    func status() async throws -> BulbState {
        BulbState.parse(try await getProps())
    }

    func setPower(_ on: Bool, effect: String = "smooth", duration: Int = 300) async throws {
        _ = try await send("set_power", [on ? "on" : "off", effect, duration])
    }

    func toggle() async throws {
        _ = try await send("toggle", [])
    }

    func setBright(_ value: Int, effect: String = "smooth", duration: Int = 300) async throws {
        _ = try await send("set_bright", [Proto.clamp(value, 1, 100), effect, duration])
    }

    func setRGB(_ value: Int, effect: String = "smooth", duration: Int = 300) async throws {
        _ = try await send("set_rgb", [Proto.clamp(value, 0, 0xFFFFFF), effect, duration])
    }

    func setCT(_ kelvin: Int, effect: String = "smooth", duration: Int = 300) async throws {
        _ = try await send("set_ct_abx", [Proto.clamp(kelvin, 1700, 6500), effect, duration])
    }

    func setHSV(hue: Int, sat: Int, effect: String = "smooth", duration: Int = 300) async throws {
        _ = try await send("set_hsv", [Proto.clamp(hue, 0, 359), Proto.clamp(sat, 0, 100), effect, duration])
    }

    func setScene(_ params: [Any]) async throws {
        _ = try await send("set_scene", params)
    }

    func setName(_ name: String) async throws {
        _ = try await send("set_name", [name])
    }

    func startFlow(count: Int, action: Int, expression: String) async throws {
        _ = try await send("start_cf", [count, action, expression])
    }

    func stopFlow() async throws {
        _ = try await send("stop_cf", [])
    }

    func setTimer(minutes: Int, brightness: Int = 100) async throws {
        _ = try await send("set_scene", ["auto_delay_off", Proto.clamp(brightness, 1, 100), max(1, minutes)])
    }

    func raw(method: String, params: [Any]) async throws -> Any {
        try await send(method, params)
    }
}
