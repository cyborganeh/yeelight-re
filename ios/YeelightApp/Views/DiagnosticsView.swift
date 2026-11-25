import SwiftUI

struct DiagnosticsView: View {
    @EnvironmentObject private var store: AppStore

    var body: some View {
        VStack(spacing: 12) {
            Card("miIO", subtitle: "Jalur darurat UDP 54321 — tanpa akun, tanpa cloud") {
                if store.miioBusy {
                    ProgressView().tint(Theme.accent)
                }

                HStack(spacing: 8) {
                    Button("Cek miIO") {
                        Task { await store.probeMiio() }
                    }
                    .buttonStyle(GhostButtonStyle())

                    Button("Buka LAN Control") {
                        Task { await store.unlockLanControl() }
                    }
                    .buttonStyle(PrimaryButtonStyle())
                }
                .disabled(store.miioBusy || store.ip.isEmpty)
                .opacity(store.miioBusy ? 0.6 : 1)

                Text("Token (opsional, 32 hex)")
                    .font(.caption)
                    .foregroundStyle(Theme.muted)
                TextField("token dari perangkat Anda sendiri", text: $store.miioToken)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                    .font(.system(.footnote, design: .monospaced))
                    .fieldStyle()

                Text(
                    "Banyak firmware YLDP06YL tidak membocorkan token saat handshake. Kalau unlock gagal, nyalakan LAN Control sekali lewat aplikasi resmi — setelah itu port 55443 tetap aktif walau tanpa cloud."
                )
                .font(.caption2)
                .foregroundStyle(Theme.muted)

                if !store.miioReport.isEmpty {
                    Text(store.miioReport)
                        .font(.system(size: 11, design: .monospaced))
                        .foregroundStyle(Theme.fg)
                        .padding(10)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .background(Theme.field)
                        .clipShape(RoundedRectangle(cornerRadius: 9, style: .continuous))
                }
            }

            Card("Log aktivitas", subtitle: "Terbaru di atas") {
                HStack {
                    Text("\(store.log.count) baris")
                        .font(.caption2)
                        .foregroundStyle(Theme.muted)
                    Spacer()
                    Button("Bersihkan") { store.clearLog() }
                        .font(.caption2.weight(.semibold))
                        .foregroundStyle(Theme.accent)
                }

                if store.log.isEmpty {
                    Text("Belum ada aktivitas.")
                        .font(.caption)
                        .foregroundStyle(Theme.muted)
                } else {
                    VStack(alignment: .leading, spacing: 6) {
                        ForEach(store.log.prefix(60)) { line in
                            HStack(alignment: .top, spacing: 6) {
                                Text(line.date.formatted(date: .omitted, time: .standard))
                                    .font(.system(size: 10, design: .monospaced))
                                    .foregroundStyle(Theme.muted)
                                Text(line.text)
                                    .font(.system(size: 11, design: .monospaced))
                                    .foregroundStyle(color(for: line.level))
                                    .frame(maxWidth: .infinity, alignment: .leading)
                            }
                        }
                    }
                    .padding(10)
                    .background(Theme.field)
                    .clipShape(RoundedRectangle(cornerRadius: 9, style: .continuous))
                }
            }
        }
    }

    private func color(for level: LogLine.Level) -> Color {
        switch level {
        case .info: return Theme.fg
        case .ok: return Theme.green
        case .warn: return Theme.accent
        case .error: return Theme.red
        }
    }
}
