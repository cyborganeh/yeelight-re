import Foundation

/// Konstanta dan helper protokol LAN Yeelight (setara protocol.py).
enum Proto {
    static let controlPort: UInt16 = 55443
    static let miioPort: UInt16 = 54321

    static let statusProps: [String] = [
        "power", "bright", "ct", "rgb", "hue", "sat", "color_mode",
        "flowing", "delayoff", "music_on", "name",
    ]

    static let intProps: Set<String> = [
        "bright", "ct", "rgb", "hue", "sat", "color_mode",
        "flowing", "delayoff", "music_on",
    ]

    static let errorText: [Int: String] = [
        -1: "general error",
        -2: "kuota klien habis (maks 60 perintah/menit)",
        -3: "parameter tidak valid",
        -4: "metode tidak didukung firmware ini",
        -5: "lampu offline / error internal",
    ]

    static func clamp(_ value: Int, _ low: Int, _ high: Int) -> Int {
        min(high, max(low, value))
    }

    /// Satu perintah JSON-RPC, diakhiri CRLF seperti yang diwajibkan lampu.
    static func command(id: Int, method: String, params: [Any]) throws -> Data {
        let object: [String: Any] = ["id": id, "method": method, "params": params]
        let body = try JSONSerialization.data(withJSONObject: object, options: [])
        return body + Data([0x0D, 0x0A])
    }

    // MARK: - Warna

    static func components(_ rgb: Int) -> (red: Int, green: Int, blue: Int) {
        ((rgb >> 16) & 0xFF, (rgb >> 8) & 0xFF, rgb & 0xFF)
    }

    static func rgb(red: Int, green: Int, blue: Int) -> Int {
        (clamp(red, 0, 255) << 16) | (clamp(green, 0, 255) << 8) | clamp(blue, 0, 255)
    }

    static func hex(_ rgb: Int) -> String {
        String(format: "#%06x", UInt32(rgb & 0xFFFFFF))
    }

    /// RGB -> HSV (h 0...359, s 0...100, v 0...100).
    static func hsv(from rgb: Int) -> (hue: Int, sat: Int, value: Int) {
        let (r, g, b) = components(rgb)
        let rf = Double(r) / 255, gf = Double(g) / 255, bf = Double(b) / 255
        let maximum = max(rf, gf, bf), minimum = min(rf, gf, bf)
        let delta = maximum - minimum
        var hue = 0.0
        if delta > 0 {
            if maximum == rf {
                hue = 60 * ((gf - bf) / delta).truncatingRemainder(dividingBy: 6)
            } else if maximum == gf {
                hue = 60 * ((bf - rf) / delta + 2)
            } else {
                hue = 60 * ((rf - gf) / delta + 4)
            }
        }
        if hue < 0 { hue += 360 }
        let saturation = maximum == 0 ? 0 : delta / maximum
        return (Int(hue.rounded()) % 360, Int((saturation * 100).rounded()), Int((maximum * 100).rounded()))
    }

    /// Flow expression: durasi(ms), mode, nilai, kecerahan.
    static func buildFlow(_ steps: [(duration: Int, mode: Int, value: Int, bright: Int)]) -> String {
        steps.map { "\($0.duration),\($0.mode),\($0.value),\($0.bright)" }.joined(separator: ",")
    }
}

// MARK: - State lampu

struct BulbState: Equatable {
    var power = "off"
    var bright = 0
    var ct = 4000
    var rgb = 0xFFFFFF
    var hue = 0
    var sat = 0
    var colorMode = 0
    var flowing = 0
    var musicOn = 0
    var delayOff = 0
    var name = ""
    var model = ""

    var isOn: Bool { power == "on" }

    var modeText: String {
        switch colorMode {
        case 1: return "suhu warna"
        case 2: return "RGB"
        case 3: return "HSV"
        default: return "normal"
        }
    }

    static func parse(_ raw: [String: Any]) -> BulbState {
        func int(_ key: String, _ fallback: Int) -> Int {
            if let value = raw[key] as? Int { return value }
            if let value = raw[key] as? NSNumber { return value.intValue }
            if let text = raw[key] as? String, let value = Int(text) { return value }
            return fallback
        }
        func text(_ key: String) -> String {
            raw[key] as? String ?? ""
        }
        var state = BulbState()
        state.power = text("power").isEmpty ? "off" : text("power")
        state.bright = int("bright", 0)
        state.ct = int("ct", 4000)
        state.rgb = int("rgb", 0xFFFFFF)
        state.hue = int("hue", 0)
        state.sat = int("sat", 0)
        state.colorMode = int("color_mode", 0)
        state.flowing = int("flowing", 0)
        state.musicOn = int("music_on", 0)
        state.delayOff = int("delayoff", 0)
        state.name = text("name")
        state.model = text("model")
        return state
    }
}

// MARK: - Preset scene & flow (sama dengan presets.py)

struct ScenePreset: Identifiable {
    enum Kind {
        case ct(kelvin: Int, bright: Int)
        case color(rgb: Int, bright: Int)
    }

    let id: String
    let title: String
    let detail: String
    let kind: Kind

    var params: [Any] {
        switch kind {
        case let .ct(kelvin, bright):
            return ["ct", kelvin, bright]
        case let .color(rgb, bright):
            return ["color", rgb, bright]
        }
    }

    static let all: [ScenePreset] = [
        .init(id: "reading", title: "Baca", detail: "4000 K · 100%", kind: .ct(kelvin: 4000, bright: 100)),
        .init(id: "relax", title: "Santai", detail: "2700 K · 40%", kind: .ct(kelvin: 2700, bright: 40)),
        .init(id: "night", title: "Malam", detail: "1900 K · 5%", kind: .ct(kelvin: 1900, bright: 5)),
        .init(id: "focus", title: "Fokus", detail: "5000 K · 100%", kind: .ct(kelvin: 5000, bright: 100)),
        .init(id: "movie", title: "Film", detail: "#1414ff · 15%", kind: .color(rgb: 0x1414FF, bright: 15)),
        .init(id: "sunset", title: "Senja", detail: "#ff5a1f · 40%", kind: .color(rgb: 0xFF5A1F, bright: 40)),
        .init(id: "forest", title: "Hutan", detail: "#1f7a3d · 45%", kind: .color(rgb: 0x1F7A3D, bright: 45)),
        .init(id: "ocean", title: "Laut", detail: "#0066cc · 45%", kind: .color(rgb: 0x0066CC, bright: 45)),
        .init(id: "candle", title: "Lilin", detail: "#ff9329 · 30%", kind: .color(rgb: 0xFF9329, bright: 30)),
    ]
}

struct FlowPreset: Identifiable {
    let id: String
    let title: String
    let count: Int
    let action: Int
    let expression: String

    static let all: [FlowPreset] = [
        .init(
            id: "party", title: "Party", count: 0, action: 1,
            expression: Proto.buildFlow([
                (700, 1, 0xFF0000, 100), (700, 1, 0x00FF00, 100), (700, 1, 0x0000FF, 100),
                (700, 1, 0xFFFF00, 100), (700, 1, 0xFF00FF, 100), (700, 1, 0x00FFFF, 100),
            ])
        ),
        .init(
            id: "rainbow", title: "Rainbow", count: 0, action: 1,
            expression: Proto.buildFlow([
                (500, 1, 0xFF0000, 100), (500, 1, 0xFF7F00, 100), (500, 1, 0xFFFF00, 100),
                (500, 1, 0x00FF00, 100), (500, 1, 0x0000FF, 100), (500, 1, 0x4B0082, 100),
                (500, 1, 0x9400D3, 100),
            ])
        ),
        .init(
            id: "sunrise", title: "Sunrise", count: 1, action: 1,
            expression: Proto.buildFlow([(120000, 2, 2700, 1), (120000, 2, 4000, 100)])
        ),
        .init(
            id: "sunset", title: "Sunset", count: 1, action: 1,
            expression: Proto.buildFlow([(120000, 2, 2700, 100), (120000, 2, 2700, 1)])
        ),
        .init(
            id: "candle", title: "Candle", count: 0, action: 1,
            expression: Proto.buildFlow([
                (250, 2, 2200, 35), (350, 2, 2400, 55), (180, 2, 2100, 25),
                (420, 2, 2500, 65), (260, 2, 2300, 40),
            ])
        ),
    ]
}
