import Foundation
import SwiftUI

struct LogLine: Identifiable {
    enum Level {
        case info, ok, warn, error
    }

    let id = UUID()
    let date = Date()
    let text: String
    let level: Level
}

/// Sumber kebenaran tunggal untuk UI dan koneksi.
@MainActor
final class AppStore: ObservableObject {
    enum Status: Equatable {
        case idle
        case scanning
        case connecting
        case connected
        case failed(String)
    }

    // MARK: - State yang tampil

    @Published var ip: String {
        didSet { defaults.set(ip, forKey: Keys.ip) }
    }
    @Published var portText: String {
        didSet { defaults.set(portText, forKey: Keys.port) }
    }
    @Published var subnet: String {
        didSet { defaults.set(subnet, forKey: Keys.subnet) }
    }

    @Published private(set) var status: Status = .idle
    @Published private(set) var state = BulbState()
    @Published private(set) var hits: [BulbHit] = []
    @Published private(set) var log: [LogLine] = []
    @Published private(set) var scanning = false
    @Published private(set) var busy = false
    @Published private(set) var lanControlBlocked = false
    @Published private(set) var progressDone = 0
    @Published private(set) var progressTotal = 0
    @Published private(set) var miioBusy = false
    @Published var lastRawResult = ""
    @Published var miioToken: String {
        didSet { defaults.set(miioToken, forKey: Keys.token) }
    }
    @Published var miioReport = ""

    // MARK: - Internal

    private let defaults = UserDefaults.standard
    private var client: BulbClient?
    private var pollTask: Task<Void, Never>?

    private enum Keys {
        static let ip = "yeelight.ip"
        static let port = "yeelight.port"
        static let subnet = "yeelight.subnet"
        static let token = "yeelight.miioToken"
    }

    init() {
        ip = defaults.string(forKey: Keys.ip) ?? ""
        portText = defaults.string(forKey: Keys.port) ?? String(Proto.controlPort)
        subnet = defaults.string(forKey: Keys.subnet) ?? ""
        miioToken = defaults.string(forKey: Keys.token) ?? ""
        addLog("Siap. Isi IP lampu atau pindai jaringan.", .info)
    }

    // MARK: - Turunan untuk UI

    var isConnected: Bool {
        if case .connected = status { return true }
        return false
    }

    var statusText: String {
        switch status {
        case .idle: return "Belum terhubung"
        case .scanning: return "Memindai…"
        case .connecting: return "Menghubungkan…"
        case .connected: return ip.isEmpty ? "Terhubung" : "Terhubung · \(ip)"
        case let .failed(message): return message
        }
    }

    var statusColor: Color {
        switch status {
        case .connected: return Theme.green
        case .scanning, .connecting: return Theme.accent
        case .failed: return Theme.red
        case .idle: return Theme.muted
        }
    }

    var scanLabel: String {
        if scanning {
            return progressTotal > 0 ? "Memindai \(progressDone)/\(progressTotal)" : "Memindai…"
        }
        return "Pindai lampu"
    }

    var progressValue: Double {
        guard progressTotal > 0 else { return 0 }
        return Double(progressDone) / Double(progressTotal)
    }

    // MARK: - Log

    func addLog(_ text: String, _ level: LogLine.Level = .info) {
        log.insert(LogLine(text: text, level: level), at: 0)
        if log.count > 400 {
            log.removeLast(log.count - 400)
        }
    }

    func clearLog() {
        log.removeAll()
    }

    private func describe(_ error: Error) -> String {
        (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
    }

    private static func isLanControlDisabled(_ error: Error) -> Bool {
        if case BulbError.lanControlDisabled = error { return true }
        return false
    }

    // MARK: - Koneksi

    func bootstrap() async {
        guard !ip.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return }
        await connect(autoScan: true)
    }

    func connect(autoScan: Bool = false) async {
        let target = ip.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !target.isEmpty else {
            addLog("IP masih kosong. Pindai jaringan atau isi manual.", .warn)
            return
        }
        let port = UInt16(portText.trimmingCharacters(in: .whitespaces)) ?? Proto.controlPort

        stopPolling()
        if let old = client {
            await old.close()
            client = nil
        }
        status = .connecting

        let newClient = BulbClient(host: target, port: port)
        await newClient.setDisconnectHandler { [weak self, weak newClient] message in
            Task { @MainActor in
                guard let self, let newClient else { return }
                guard self.client === newClient else { return }
                self.status = .failed("Terputus")
                self.addLog("Koneksi terputus: \(message). Coba pindai ulang.", .error)
            }
        }

        do {
            try await newClient.connect()
            let fresh = try await newClient.status()
            client = newClient
            state = fresh
            lanControlBlocked = false
            status = .connected
            addLog("Terhubung ke \(target):\(port). State awal diterima.", .ok)
            startPolling()
        } catch {
            await newClient.close()
            let message = describe(error)
            if Self.isLanControlDisabled(error) {
                lanControlBlocked = true
                status = .failed("LAN Control mati")
                addLog("Port 55443 menolak koneksi = LAN Control belum aktif. Buka tab miIO untuk membukanya.", .error)
            } else {
                status = .failed(message)
                addLog("Koneksi gagal ke \(target): \(message)", .error)
            }
            if autoScan {
                addLog("IP tersimpan tidak menjawab. Memindai jaringan otomatis…", .info)
                await scan(autoConnect: true)
            }
        }
    }

    func disconnect() async {
        stopPolling()
        if let old = client {
            await old.close()
            client = nil
        }
        status = .idle
        addLog("Terputus.", .info)
    }

    private func startPolling() {
        pollTask?.cancel()
        pollTask = Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(nanoseconds: 2_500_000_000)
                guard let self, let active = self.client else { return }
                do {
                    let fresh = try await active.status()
                    if self.client === active {
                        self.state = fresh
                    }
                } catch {
                    if !Task.isCancelled {
                        self.addLog("Sinkronisasi state gagal: \(self.describe(error))", .warn)
                    }
                    return
                }
            }
        }
    }

    private func stopPolling() {
        pollTask?.cancel()
        pollTask = nil
    }

    // MARK: - Pindai

    func scan(autoConnect: Bool = true) async {
        guard !scanning else { return }
        scanning = true
        status = .scanning
        hits = []
        progressDone = 0
        progressTotal = 0

        let target = subnet.trimmingCharacters(in: .whitespacesAndNewlines)
        addLog("Memindai \(target.isEmpty ? "semua antarmuka lokal (/24)" : target) pada TCP \(Proto.controlPort)…", .info)

        let result = await Discovery.scan(subnet: target.isEmpty ? nil : target) { done, total in
            Task { @MainActor in
                self.progressDone = done
                self.progressTotal = total
            }
        }

        hits = result
        scanning = false
        let bulbs = result.filter(\.isBulb)
        let others = result.filter { !$0.isBulb }

        for bulb in bulbs {
            addLog("Lampu ditemukan: \(bulb.label)", .ok)
        }
        for other in others {
            addLog("Port terbuka tapi bukan Yeelight: \(other.ip)", .warn)
        }

        guard !bulbs.isEmpty else {
            status = .failed("Tidak ada lampu")
            if others.isEmpty {
                addLog(
                    "Tidak ada host dengan TCP 55443. Pastikan iPhone dan lampu di Wi-Fi yang sama, izin Local Network aktif, lalu coba isi subnet manual (mis. 192.168.1.0/24).",
                    .error
                )
            } else {
                addLog("Host di atas membuka port tetapi tidak menjawab get_prop. LAN Control mungkin mati.", .error)
            }
            return
        }

        if bulbs.count == 1 {
            let bulb = bulbs[0]
            if !ip.isEmpty && ip != bulb.ip {
                addLog("IP berubah: \(ip) → \(bulb.ip). Menghubungkan ulang…", .ok)
            }
            ip = bulb.ip
            if autoConnect {
                await connect()
            }
        } else {
            if !bulbs.contains(where: { $0.ip == ip }) {
                ip = bulbs[0].ip
            }
            status = .failed("\(bulbs.count) lampu ditemukan")
            addLog("Lebih dari satu lampu ditemukan — pilih IP di daftar lalu klik Hubungkan.", .info)
        }
    }

    // MARK: - Perintah

    func perform(_ label: String, _ action: @escaping @Sendable (BulbClient) async throws -> Void) {
        guard let active = client, isConnected else {
            addLog("Belum terhubung ke lampu.", .warn)
            return
        }
        busy = true
        Task {
            do {
                try await action(active)
                addLog("\(label): OK", .ok)
                if let fresh = try? await active.status(), client === active {
                    state = fresh
                }
            } catch {
                addLog("\(label) gagal: \(describe(error))", .error)
                if Self.isLanControlDisabled(error) {
                    lanControlBlocked = true
                }
            }
            busy = false
        }
    }

    func setPower(_ on: Bool) {
        perform(on ? "Nyalakan" : "Matikan") { try await $0.setPower(on) }
    }

    func toggle() {
        perform("Toggle") { try await $0.toggle() }
    }

    func setBright(_ value: Int) {
        perform("Kecerahan \(value)%") { try await $0.setBright(value) }
    }

    func setRGB(_ value: Int) {
        perform("Warna \(Proto.hex(value))") { try await $0.setRGB(value) }
    }

    func setCT(_ kelvin: Int) {
        perform("Suhu \(kelvin) K") { try await $0.setCT(kelvin) }
    }

    func setHSV(hue: Int, sat: Int) {
        perform("HSV \(hue)/\(sat)") { try await $0.setHSV(hue: hue, sat: sat) }
    }

    func apply(_ scene: ScenePreset) {
        perform("Scene \(scene.title)") { try await $0.setScene(scene.params) }
    }

    func start(_ flow: FlowPreset) {
        perform("Flow \(flow.title)") {
            try await $0.startFlow(count: flow.count, action: flow.action, expression: flow.expression)
        }
    }

    func stopFlow() {
        perform("Stop flow") { try await $0.stopFlow() }
    }

    func setTimer(minutes: Int) {
        perform("Timer \(minutes) menit") { try await $0.setTimer(minutes: minutes) }
    }

    func rename(_ name: String) {
        let trimmed = name.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }
        perform("Ganti nama") { try await $0.setName(trimmed) }
    }

    func sendRaw(method: String, paramsText: String) {
        let trimmedMethod = method.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedMethod.isEmpty else {
            addLog("Nama method masih kosong.", .warn)
            return
        }
        guard let active = client, isConnected else {
            addLog("Belum terhubung ke lampu.", .warn)
            return
        }

        var params: [Any] = []
        let text = paramsText.trimmingCharacters(in: .whitespacesAndNewlines)
        if !text.isEmpty {
            guard
                let data = text.data(using: .utf8),
                let object = try? JSONSerialization.jsonObject(with: data)
            else {
                addLog("Params bukan JSON yang valid.", .error)
                return
            }
            if let array = object as? [Any] {
                params = array
            } else {
                params = [object]
            }
        }

        busy = true
        Task {
            defer { busy = false }
            do {
                let result = try await active.raw(method: trimmedMethod, params: params)
                let pretty = Self.pretty(result)
                lastRawResult = pretty
                addLog("Hasil \(trimmedMethod): \(pretty)", .info)
                let fresh = try await active.status()
                if client === active { state = fresh }
            } catch {
                lastRawResult = describe(error)
                addLog("Raw \(trimmedMethod) gagal: \(describe(error))", .error)
            }
        }
    }

    private static func pretty(_ value: Any) -> String {
        if let data = try? JSONSerialization.data(withJSONObject: value, options: [.prettyPrinted]),
           let text = String(data: data, encoding: .utf8) {
            return text.replacingOccurrences(of: "\n", with: " ")
        }
        return String(describing: value)
    }

    // MARK: - miIO

    func probeMiio() async {
        let host = ip.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !host.isEmpty else {
            addLog("Isi IP lampu dulu.", .warn)
            return
        }
        miioBusy = true
        addLog("Handshake miIO ke \(host):\(Proto.miioPort)…", .info)
        let result = await Miio.probe(host: host)
        miioBusy = false

        if result.available {
            miioReport = """
            miIO menjawab.
            device id : 0x\(result.deviceID)
            token     : \(result.tokenExposed ? result.token : "tidak dibocorkan (0x00)")
            """
            addLog("miIO tersedia (device 0x\(result.deviceID)).", .ok)
        } else {
            miioReport = "miIO tidak menjawab: \(result.error)"
            addLog("miIO gagal: \(result.error)", .error)
        }
    }

    func unlockLanControl() async {
        let host = ip.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !host.isEmpty else {
            addLog("Isi IP lampu dulu.", .warn)
            return
        }
        miioBusy = true
        miioReport = "Menghubungi miIO…"
        addLog("Mencoba membuka LAN Control lewat miIO (tanpa app, tanpa cloud)…", .info)

        do {
            let report = try await Miio.enableLANControl(host: host, token: miioToken)
            miioReport = report
            let success = report.contains("AKTIF")
            addLog(report, success ? .ok : .warn)
            if success {
                lanControlBlocked = false
                await connect()
            }
        } catch {
            let message = describe(error)
            miioReport = message
            addLog("Unlock gagal: \(message)", .error)
        }
        miioBusy = false
    }
}
