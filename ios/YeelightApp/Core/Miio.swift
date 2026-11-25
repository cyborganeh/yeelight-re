import Foundation

/// miIO (UDP 54321) secukupnya untuk membuka LAN Control tanpa aplikasi resmi.
enum Miio {
    static let magic: UInt16 = 0x2131
    static let helloPacket = Data([0x21, 0x31, 0x00, 0x20] + [UInt8](repeating: 0xFF, count: 28))
    static let zeroToken = Data(repeating: 0x00, count: 16)
    static let emptyToken = Data(repeating: 0xFF, count: 16)

    struct Handshake {
        let deviceID: Data
        let stamp: UInt32
        let tokenCandidate: Data

        var deviceIDHex: String { deviceID.map { String(format: "%02x", $0) }.joined() }

        var tokenExposed: Bool {
            tokenCandidate != Miio.zeroToken && tokenCandidate != Miio.emptyToken
        }

        var tokenHex: String {
            tokenExposed ? tokenCandidate.map { String(format: "%02x", $0) }.joined() : ""
        }
    }

    struct Probe {
        let available: Bool
        let deviceID: String
        let tokenExposed: Bool
        let token: String
        let error: String
    }

    // MARK: - Token & kripto

    static func normaliseToken(_ text: String?) throws -> Data? {
        let trimmed = (text ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
            .lowercased()
            .replacingOccurrences(of: "0x", with: "")
        if trimmed.isEmpty { return nil }
        guard trimmed.count == 32, let data = Data(hexString: trimmed) else {
            throw BulbError.miioToken("token harus 32 karakter heksadesimal")
        }
        return data
    }

    private static func keyIV(for token: Data) -> (key: Data, iv: Data) {
        let key = Crypto.md5(token)
        let iv = Crypto.md5(key + token)
        return (key, iv)
    }

    static func encrypt(_ plaintext: Data, token: Data) throws -> Data {
        let (key, iv) = keyIV(for: token)
        guard let encrypted = Crypto.aesCBC(plaintext, key: key, iv: iv, decrypt: false) else {
            throw BulbError.miioToken("enkripsi AES gagal")
        }
        return encrypted
    }

    static func decrypt(_ ciphertext: Data, token: Data) throws -> Data {
        let (key, iv) = keyIV(for: token)
        guard let decrypted = Crypto.aesCBC(ciphertext, key: key, iv: iv, decrypt: true) else {
            throw BulbError.miioToken("dekripsi AES gagal")
        }
        return decrypted
    }

    static func buildPacket(deviceID: Data, stamp: UInt32, token: Data, request: [String: Any]) throws -> Data {
        guard deviceID.count == 4 else { throw BulbError.miioToken("device id harus 4 byte") }
        guard token.count == 16 else { throw BulbError.miioToken("token harus 16 byte") }

        let json = try JSONSerialization.data(withJSONObject: request, options: [])
        var plaintext = json
        plaintext.append(0x00)
        let encrypted = try encrypt(plaintext, token: token)

        let totalLength = UInt16(32 + encrypted.count)
        var header = Data()
        header.appendUInt16BE(magic)
        header.appendUInt16BE(totalLength)
        header.appendUInt32BE(0)
        header.append(deviceID)
        header.appendUInt32BE(stamp)

        let checksum = Crypto.md5(header + token + encrypted)
        return header + checksum + encrypted
    }

    static func parseReply(_ data: Data, token: Data) throws -> [String: Any] {
        guard data.count >= 32 else { throw BulbError.miioUnavailable("balasan miIO terlalu pendek") }
        guard data.uint16BE(at: 0) == magic else { throw BulbError.miioUnavailable("magic miIO tidak dikenal") }
        let length = Int(data.uint16BE(at: 2))
        guard length == 0 || (length >= 32 && length <= data.count) else {
            throw BulbError.miioUnavailable("balasan miIO terpotong")
        }

        let end = length == 0 ? data.count : length
        let encrypted = data.subdata(in: 32..<end)
        guard !encrypted.isEmpty else { throw BulbError.miioUnavailable("balasan miIO tanpa payload") }

        let checksum = data.subdata(in: 16..<32)
        let expected = Crypto.md5(data.subdata(in: 0..<16) + token + encrypted)
        guard checksum == expected else {
            throw BulbError.miioToken("token ditolak lampu (checksum tidak cocok)")
        }

        let plaintext = try decrypt(encrypted, token: token)
        let trimmed = plaintext.prefix { $0 != 0x00 }
        guard
            let object = try? JSONSerialization.jsonObject(with: Data(trimmed)),
            let payload = object as? [String: Any]
        else {
            throw BulbError.miioUnavailable("payload miIO tidak bisa dibaca")
        }
        return payload
    }

    // MARK: - Transport UDP

    private static func exchange(host: String, port: UInt16, payload: Data, timeout: TimeInterval) async throws -> Data {
        try await withCheckedThrowingContinuation { continuation in
            DispatchQueue.global(qos: .userInitiated).async {
                do {
                    let data = try blockingExchange(host: host, port: port, payload: payload, timeout: timeout)
                    continuation.resume(returning: data)
                } catch {
                    continuation.resume(throwing: error)
                }
            }
        }
    }

    private static func blockingExchange(host: String, port: UInt16, payload: Data, timeout: TimeInterval) throws -> Data {
        let descriptor = socket(AF_INET, SOCK_DGRAM, 0)
        guard descriptor >= 0 else {
            throw BulbError.miioUnavailable("tidak bisa membuat socket UDP")
        }
        defer { close(descriptor) }

        var tv = timeval(tv_sec: Int(max(0.3, timeout)), tv_usec: 0)
        setsockopt(descriptor, SOL_SOCKET, SO_RCVTIMEO, &tv, socklen_t(MemoryLayout<timeval>.size))
        setsockopt(descriptor, SOL_SOCKET, SO_SNDTIMEO, &tv, socklen_t(MemoryLayout<timeval>.size))

        var address = sockaddr_in()
        address.sin_len = UInt8(MemoryLayout<sockaddr_in>.size)
        address.sin_family = sa_family_t(AF_INET)
        address.sin_port = port.bigEndian
        guard inet_pton(AF_INET, host, &address.sin_addr) == 1 else {
            throw BulbError.miioUnavailable("alamat IP tidak valid: \(host)")
        }

        let sent = payload.withUnsafeBytes { raw -> Int in
            withUnsafePointer(to: &address) { pointer in
                pointer.withMemoryRebound(to: sockaddr.self, capacity: 1) { socketAddress in
                    sendto(
                        descriptor,
                        raw.baseAddress,
                        payload.count,
                        0,
                        socketAddress,
                        socklen_t(MemoryLayout<sockaddr_in>.size)
                    )
                }
            }
        }
        guard sent > 0 else {
            throw BulbError.miioUnavailable("gagal mengirim paket ke \(host):\(port)")
        }

        var buffer = [UInt8](repeating: 0, count: 4096)
        let received = recv(descriptor, &buffer, buffer.count, 0)
        guard received > 0 else {
            throw BulbError.miioUnavailable("\(host):\(port) tidak menjawab (UDP diblokir atau miIO mati)")
        }
        return Data(buffer.prefix(received))
    }

    // MARK: - API

    static func handshake(host: String, port: UInt16 = Proto.miioPort, timeout: TimeInterval = 3, retries: Int = 2) async throws -> Handshake {
        var lastError: Error = BulbError.miioUnavailable("tidak ada balasan")
        for _ in 0..<max(1, retries) {
            do {
                let data = try await exchange(host: host, port: port, payload: helloPacket, timeout: timeout)
                guard data.count >= 32 else {
                    lastError = BulbError.miioUnavailable("balasan hello terlalu pendek")
                    continue
                }
                guard data.uint16BE(at: 0) == magic else {
                    lastError = BulbError.miioUnavailable("magic hello tidak dikenal")
                    continue
                }
                let deviceID = data.subdata(in: 8..<12)
                let stamp = data.uint32BE(at: 12)
                let candidate = data.subdata(in: 16..<32)
                return Handshake(deviceID: deviceID, stamp: stamp, tokenCandidate: candidate)
            } catch {
                lastError = error
            }
        }
        throw lastError
    }

    static func probe(host: String, timeout: TimeInterval = 3) async -> Probe {
        do {
            let info = try await handshake(host: host, timeout: timeout)
            return Probe(
                available: true,
                deviceID: info.deviceIDHex,
                tokenExposed: info.tokenExposed,
                token: info.tokenHex,
                error: ""
            )
        } catch {
            return Probe(
                available: false,
                deviceID: "",
                tokenExposed: false,
                token: "",
                error: (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
            )
        }
    }

    /// Kirim `set_ps ["cfg_lan_ctrl", "1"]`, lalu verifikasi TCP 55443 terbuka.
    static func enableLANControl(
        host: String,
        token explicitToken: String,
        timeout: TimeInterval = 3
    ) async throws -> String {
        let info = try await handshake(host: host, timeout: timeout)
        let explicit = try normaliseToken(explicitToken)
        guard let token = explicit ?? (info.tokenExposed ? info.tokenCandidate : nil) else {
            throw BulbError.miioToken(
                "firmware ini tidak membocorkan token saat handshake. Isi token manual (32 hex) atau nyalakan LAN Control sekali lewat aplikasi resmi."
            )
        }

        let stamp = info.stamp &+ 1
        let request: [String: Any] = [
            "id": 1,
            "method": "set_ps",
            "params": ["cfg_lan_ctrl", "1"],
        ]
        let packet = try buildPacket(deviceID: info.deviceID, stamp: stamp, token: token, request: request)
        let reply = try await exchange(host: host, port: Proto.miioPort, payload: packet, timeout: timeout)
        let payload = try parseReply(reply, token: token)

        if let error = payload["error"] as? [String: Any] {
            let code = (error["code"] as? Int) ?? -1
            let message = (error["message"] as? String) ?? "unknown"
            throw BulbError.miioToken("lampu menolak perintah: error \(code) \(message)")
        }

        // Beri firmware waktu singkat untuk membuka port.
        var opened = false
        let deadline = Date().addingTimeInterval(3)
        while Date() < deadline {
            if await Discovery.probe(host: host, timeout: 0.8) {
                opened = true
                break
            }
            try? await Task.sleep(nanoseconds: 400_000_000)
        }

        return opened
            ? "LAN Control AKTIF. TCP 55443 sekarang menerima koneksi — silakan Hubungkan."
            : "Perintah terkirim, tetapi TCP 55443 belum terbuka. Coba lagi atau isi token yang benar."
    }
}

// MARK: - Helper biner

extension Data {
    mutating func appendUInt16BE(_ value: UInt16) {
        append(UInt8((value >> 8) & 0xFF))
        append(UInt8(value & 0xFF))
    }

    mutating func appendUInt32BE(_ value: UInt32) {
        append(UInt8((value >> 24) & 0xFF))
        append(UInt8((value >> 16) & 0xFF))
        append(UInt8((value >> 8) & 0xFF))
        append(UInt8(value & 0xFF))
    }

    func uint16BE(at offset: Int) -> UInt16 {
        guard offset + 1 < count else { return 0 }
        let high = UInt16(self[startIndex + offset])
        let low = UInt16(self[startIndex + offset + 1])
        return high << 8 | low
    }

    func uint32BE(at offset: Int) -> UInt32 {
        guard offset + 3 < count else { return 0 }
        let bytes = (0..<4).map { UInt32(self[startIndex + offset + $0]) }
        return bytes[0] << 24 | bytes[1] << 16 | bytes[2] << 8 | bytes[3]
    }

    init?(hexString: String) {
        let characters = Array(hexString)
        guard characters.count % 2 == 0 else { return nil }
        var bytes = [UInt8]()
        bytes.reserveCapacity(characters.count / 2)
        var index = 0
        while index < characters.count {
            let pair = String(characters[index...index + 1])
            guard let byte = UInt8(pair, radix: 16) else { return nil }
            bytes.append(byte)
            index += 2
        }
        self = Data(bytes)
    }
}
