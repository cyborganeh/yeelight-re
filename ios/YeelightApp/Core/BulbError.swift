import Foundation

/// Error yang bisa muncul dari lampu, dengan pesan Bahasa Indonesia.
enum BulbError: LocalizedError {
    case lanControlDisabled
    case timeout(method: String)
    case command(code: Int, message: String, method: String?)
    case malformed(String)
    case transport(String)
    case miioUnavailable(String)
    case miioToken(String)

    var errorDescription: String? {
        switch self {
        case .lanControlDisabled:
            return "Port 55443 menolak koneksi. LAN Control kemungkinan masih mati."
        case let .timeout(method):
            return "\(method): lampu tidak menjawab (timeout)."
        case let .command(code, message, method):
            let detail = Proto.errorText[code] ?? message
            let prefix = method.map { "\($0): " } ?? ""
            return "\(prefix)error \(code) — \(detail)"
        case let .malformed(text):
            return "Balasan tidak dikenal: \(text)"
        case let .transport(text):
            return "Koneksi bermasalah: \(text)"
        case let .miioUnavailable(text):
            return "miIO tidak tersedia: \(text)"
        case let .miioToken(text):
            return "Token miIO tidak bisa dipakai: \(text)"
        }
    }
}

/// Satu host hasil pindai jaringan.
struct BulbHit: Identifiable, Hashable {
    let ip: String
    var port: UInt16 = Proto.controlPort
    var isBulb = false
    var name = ""
    var model = ""
    var power = ""
    var bright: Int?
    var note = ""
    var detail = ""

    var id: String { "\(ip):\(port)" }

    var label: String {
        guard isBulb else {
            return "\(ip) — port terbuka, bukan Yeelight"
        }
        let displayName = name.isEmpty ? "tanpa nama" : name
        let brightness = bright.map { "\($0)%" } ?? "?"
        let powerText = power == "on" ? "nyala" : (power == "off" ? "mati" : "?")
        return "\(ip) · \(displayName) · \(powerText) · \(brightness)"
    }
}
