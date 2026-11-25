import SwiftUI

struct InfoView: View {
    @EnvironmentObject private var store: AppStore
    @State private var newName = ""
    @State private var method = "get_prop"
    @State private var params = "[\"power\",\"bright\"]"

    var body: some View {
        VStack(spacing: 12) {
            Card("Perangkat", subtitle: "Dari API LAN, bukan SSDP") {
                row("IP", store.ip.isEmpty ? "—" : "\(store.ip):\(store.portText)")
                row("Model", store.state.model.isEmpty ? "—" : store.state.model)
                row("Nama", store.state.name.isEmpty ? "(tanpa nama)" : store.state.name)
                row("Daya", store.state.isOn ? "nyala" : "mati")
                row("Kecerahan", "\(store.state.bright)%")
                row("Mode warna", store.state.modeText)
                row("RGB", Proto.hex(store.state.rgb))
                row("Suhu", "\(store.state.ct) K")
                row("HSV", "\(store.state.hue), \(store.state.sat)%")
                row("Flow", store.state.flowing == 1 ? "berjalan" : "berhenti")
                row("Delay off", store.state.delayOff > 0 ? "\(store.state.delayOff) menit" : "tidak aktif")
            }

            Card("Ganti nama", subtitle: "set_name") {
                HStack(spacing: 8) {
                    TextField("mis. Lampu Kamar", text: $newName)
                        .fieldStyle()
                    Button("Simpan") {
                        store.rename(newName)
                        newName = ""
                    }
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(Color.black.opacity(0.85))
                    .padding(.horizontal, 14)
                    .padding(.vertical, 9)
                    .background(Theme.accent)
                    .clipShape(RoundedRectangle(cornerRadius: 9, style: .continuous))
                }
                .disabled(!store.isConnected)
                .opacity(store.isConnected ? 1 : 0.5)
            }

            Card("Raw command", subtitle: "Untuk reverse engineering lanjutan") {
                TextField("method", text: $method)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                    .font(.system(.footnote, design: .monospaced))
                    .fieldStyle()

                TextField("params (JSON array)", text: $params)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                    .font(.system(.footnote, design: .monospaced))
                    .fieldStyle()

                Button("Kirim ke lampu") {
                    store.sendRaw(method: method, paramsText: params)
                }
                .buttonStyle(GhostButtonStyle())
                .disabled(!store.isConnected)
                .opacity(store.isConnected ? 1 : 0.5)

                if !store.lastRawResult.isEmpty {
                    Text(store.lastRawResult)
                        .font(.system(size: 11, design: .monospaced))
                        .foregroundStyle(Theme.fg)
                        .padding(10)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .background(Theme.field)
                        .clipShape(RoundedRectangle(cornerRadius: 9, style: .continuous))
                }

                Text("Hasil lengkap juga muncul di tab miIO → Log aktivitas.")
                    .font(.caption2)
                    .foregroundStyle(Theme.muted)
            }

            Card("Tentang", subtitle: nil) {
                Text("yeelight-re 0.1.0 (iOS) · YLDP06YL color2")
                    .font(.caption)
                    .foregroundStyle(Theme.muted)
                Text("Semua komunikasi hanya di LAN: TCP 55443 untuk kontrol, UDP 54321 untuk miIO. Tidak ada telemetri dan tidak ada koneksi ke server Yeelight/Xiaomi.")
                    .font(.caption2)
                    .foregroundStyle(Theme.muted)
            }
        }
    }

    private func row(_ title: String, _ value: String) -> some View {
        HStack {
            Text(title)
                .font(.caption)
                .foregroundStyle(Theme.muted)
            Spacer()
            Text(value)
                .font(.system(.footnote, design: .monospaced))
                .foregroundStyle(Theme.fg)
                .multilineTextAlignment(.trailing)
        }
    }
}
