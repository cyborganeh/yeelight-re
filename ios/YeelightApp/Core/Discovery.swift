import Foundation
import Network

/// Pencarian lampu dengan menyapu TCP 55443 di jaringan lokal.
///
/// Ini jalur utama aplikasi: SSDP multicast butuh entitlement khusus di iOS,
/// sedangkan pemindaian TCP selalu bekerja selama izin Local Network diberikan.
enum Discovery {

    // MARK: - Antarmuka jaringan

    /// Semua IPv4 lokal yang bisa dipakai (loopback, link-local, CGNAT dibuang).
    static func localAddresses() -> [String] {
        var results: [String] = []
        var ifaddr: UnsafeMutablePointer<ifaddrs>?
        guard getifaddrs(&ifaddr) == 0, let first = ifaddr else { return [] }
        defer { freeifaddrs(ifaddr) }

        var pointer = first
        while true {
            let interface = pointer.pointee
            if let address = interface.ifa_addr, address.pointee.sa_family == UInt8(AF_INET) {
                var host = [CChar](repeating: 0, count: Int(NI_MAXHOST))
                let length = socklen_t(address.pointee.sa_len)
                if getnameinfo(address, length, &host, socklen_t(host.count), nil, 0, NI_NUMERICHOST) == 0 {
                    let ip = String(cString: host)
                    if isUsable(ip), !results.contains(ip) {
                        results.append(ip)
                    }
                }
            }
            guard let next = interface.ifa_next else { break }
            pointer = next
        }
        return results
    }

    private static func isUsable(_ ip: String) -> Bool {
        let parts = ip.split(separator: ".").compactMap { Int($0) }
        guard parts.count == 4 else { return false }
        if parts[0] == 127 || parts[0] == 0 { return false }
        if parts[0] == 169 && parts[1] == 254 { return false }
        // 100.64.0.0/10 (CGNAT / Tailscale) tidak pernah membawa lampu.
        if parts[0] == 100 && (64...127).contains(parts[1]) { return false }
        return true
    }

    /// /24 dari setiap antarmuka, tanpa duplikat.
    static func localSubnets() -> [String] {
        var subnets: [String] = []
        for ip in localAddresses() {
            let parts = ip.split(separator: ".")
            guard parts.count == 4 else { continue }
            let base = "\(parts[0]).\(parts[1]).\(parts[2]).0/24"
            if !subnets.contains(base) { subnets.append(base) }
        }
        return subnets
    }

    // MARK: - Daftar kandidat

    /// Daftar IP yang akan diperiksa. `nil`/kosong berarti semua antarmuka lokal.
    static func candidates(subnet: String? = nil) -> [String] {
        let text = (subnet ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        if text.isEmpty {
            return localSubnets().flatMap { hosts(inSubnet: $0) }
        }
        return hosts(inSubnet: text)
    }

    /// Ubah "192.168.1.0/24", "192.168.1.5" atau "192.168.1" jadi daftar host.
    static func hosts(inSubnet text: String) -> [String] {
        let pieces = text.split(separator: "/")
        let address = String(pieces[0]).trimmingCharacters(in: .whitespaces)
        let prefix = pieces.count > 1 ? (Int(pieces[1]) ?? 24) : 24
        guard (20...32).contains(prefix) else { return [] }

        let octets = address.split(separator: ".").compactMap { Int($0) }
        guard octets.count == 4, octets.allSatisfy({ (0...255).contains($0) }) else { return [] }

        let value = UInt32(octets[0]) << 24 | UInt32(octets[1]) << 16 | UInt32(octets[2]) << 8 | UInt32(octets[3])
        let mask: UInt32 = prefix == 0 ? 0 : ~UInt32(0) << (32 - prefix)
        let network = value & mask
        let count = UInt32(1) << (32 - prefix)
        guard count > 2 else { return [] }

        var hosts: [String] = []
        hosts.reserveCapacity(Int(count))
        var index: UInt32 = 1
        while index < count - 1 {
            hosts.append(ipString(network + index))
            index += 1
        }
        return hosts
    }

    private static func ipString(_ value: UInt32) -> String {
        "\((value >> 24) & 0xFF).\((value >> 16) & 0xFF).\((value >> 8) & 0xFF).\(value & 0xFF)"
    }

    // MARK: - Probe & identifikasi

    /// `true` kalau TCP `port` menerima koneksi.
    static func probe(host: String, port: UInt16 = Proto.controlPort, timeout: TimeInterval = 0.35) async -> Bool {
        let guardBox = ResumeGate()
        let connection = NWConnection(
            host: NWEndpoint.Host(host),
            port: NWEndpoint.Port(rawValue: port)!,
            using: .tcp
        )
        return await withCheckedContinuation { (continuation: CheckedContinuation<Bool, Never>) in
            connection.stateUpdateHandler = { state in
                switch state {
                case .ready:
                    if guardBox.claim() { continuation.resume(returning: true) }
                    connection.cancel()
                case .failed, .cancelled:
                    if guardBox.claim() { continuation.resume(returning: false) }
                case .waiting:
                    // iOS melaporkan "connection refused" sebagai .waiting; anggap tertutup.
                    if guardBox.claim() { continuation.resume(returning: false) }
                    connection.cancel()
                default:
                    break
                }
            }
            connection.start(queue: DispatchQueue.global(qos: .userInitiated))
            DispatchQueue.global().asyncAfter(deadline: .now() + timeout) {
                if guardBox.claim() { continuation.resume(returning: false) }
                connection.cancel()
            }
        }
    }

    /// Tanya satu host dengan `get_prop` untuk memastikan benar-benar Yeelight.
    static func identify(ip: String, port: UInt16 = Proto.controlPort, timeout: TimeInterval = 2.5) async -> BulbHit {
        let client = BulbClient(host: ip, port: port)
        do {
            try await client.connect()
            let props = try await client.getProps(Proto.statusProps + ["model"])
            await client.close()
            let state = BulbState.parse(props)
            return BulbHit(
                ip: ip,
                port: port,
                isBulb: true,
                name: state.name,
                model: state.model,
                power: state.power,
                bright: state.bright,
                note: "",
                detail: "mode \(state.modeText) · CT \(state.ct) K"
            )
        } catch {
            await client.close()
            return BulbHit(
                ip: ip,
                port: port,
                isBulb: false,
                note: (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
            )
        }
    }

    /// Pindai jaringan: probe semua host, lalu identifikasi yang portnya terbuka.
    static func scan(
        subnet: String? = nil,
        port: UInt16 = Proto.controlPort,
        timeout: TimeInterval = 0.35,
        workers: Int = 48,
        progress: (@Sendable (Int, Int) -> Void)? = nil
    ) async -> [BulbHit] {
        let hosts = candidates(subnet: subnet)
        guard !hosts.isEmpty else { return [] }

        var open: [String] = []
        var done = 0
        let width = max(8, min(workers, 96))

        await withTaskGroup(of: (String, Bool).self) { group in
            var iterator = hosts.makeIterator()
            var running = 0

            while running < width, let host = iterator.next() {
                group.addTask { (host, await probe(host: host, port: port, timeout: timeout)) }
                running += 1
            }

            while let (host, isOpen) = await group.next() {
                running -= 1
                done += 1
                if isOpen { open.append(host) }
                progress?(done, hosts.count)
                if let next = iterator.next() {
                    group.addTask { (next, await probe(host: next, port: port, timeout: timeout)) }
                    running += 1
                }
            }
        }

        guard !open.isEmpty else { return [] }

        var hits: [BulbHit] = []
        let identifyWidth = 8
        await withTaskGroup(of: BulbHit.self) { group in
            var iterator = open.makeIterator()
            var running = 0
            while running < identifyWidth, let ip = iterator.next() {
                group.addTask { await identify(ip: ip, port: port) }
                running += 1
            }
            while let hit = await group.next() {
                running -= 1
                hits.append(hit)
                if let next = iterator.next() {
                    group.addTask { await identify(ip: next, port: port) }
                    running += 1
                }
            }
        }

        return hits.sorted { left, right in
            if left.isBulb != right.isBulb { return left.isBulb }
            return left.ip.compare(right.ip, options: .numeric) == .orderedAscending
        }
    }
}

/// Penjaga agar sebuah continuation tidak pernah di-resume dua kali.
final class ResumeGate: @unchecked Sendable {
    private let lock = NSLock()
    private var used = false

    func claim() -> Bool {
        lock.lock()
        defer { lock.unlock() }
        if used { return false }
        used = true
        return true
    }
}
