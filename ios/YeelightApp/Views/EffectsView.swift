import SwiftUI

struct EffectsView: View {
    @EnvironmentObject private var store: AppStore
    @State private var timerMinutes = 30

    private let columns = Array(repeating: GridItem(.flexible(), spacing: 8), count: 3)

    var body: some View {
        VStack(spacing: 12) {
            Card("Suasana", subtitle: "9 preset scene langsung diterapkan") {
                LazyVGrid(columns: columns, spacing: 8) {
                    ForEach(ScenePreset.all) { scene in
                        Button {
                            store.apply(scene)
                        } label: {
                            VStack(spacing: 3) {
                                Text(scene.title)
                                    .font(.subheadline.weight(.semibold))
                                    .foregroundStyle(Theme.fg)
                                Text(scene.detail)
                                    .font(.caption2)
                                    .foregroundStyle(Theme.muted)
                            }
                            .frame(maxWidth: .infinity)
                            .padding(.vertical, 12)
                            .background(Theme.panel2)
                            .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
                            .overlay(
                                RoundedRectangle(cornerRadius: 10, style: .continuous)
                                    .stroke(Theme.border, lineWidth: 1)
                            )
                        }
                    }
                }
                .disabled(!store.isConnected)
                .opacity(store.isConnected ? 1 : 0.5)
            }

            Card("Flow animasi", subtitle: "Loop warna berjalan di firmware lampu") {
                ForEach(FlowPreset.all) { flow in
                    HStack {
                        VStack(alignment: .leading, spacing: 2) {
                            Text(flow.title)
                                .font(.subheadline.weight(.semibold))
                                .foregroundStyle(Theme.fg)
                            Text(flow.count == 0 ? "loop tanpa batas" : "\(flow.count) putaran")
                                .font(.caption2)
                                .foregroundStyle(Theme.muted)
                        }
                        Spacer()
                        Button("Jalankan") { store.start(flow) }
                            .font(.caption.weight(.semibold))
                            .foregroundStyle(Color.black.opacity(0.85))
                            .padding(.horizontal, 12)
                            .padding(.vertical, 7)
                            .background(Theme.accent)
                            .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
                    }
                    .padding(.vertical, 2)
                }

                Button("Hentikan flow") { store.stopFlow() }
                    .buttonStyle(GhostButtonStyle())

                if store.state.flowing == 1 {
                    Label("Flow sedang berjalan", systemImage: "waveform")
                        .font(.caption)
                        .foregroundStyle(Theme.green)
                }
            }
            .disabled(!store.isConnected)
            .opacity(store.isConnected ? 1 : 0.5)

            Card("Timer mati otomatis", subtitle: "set_scene auto_delay_off") {
                HStack {
                    Text("\(timerMinutes) menit")
                        .font(.system(.title3, design: .rounded).weight(.semibold))
                        .foregroundStyle(Theme.fg)
                    Spacer()
                    Stepper("", value: $timerMinutes, in: 1...240, step: 1)
                        .labelsHidden()
                }

                Button("Pasang timer \(timerMinutes) menit") {
                    store.setTimer(minutes: timerMinutes)
                }
                .buttonStyle(PrimaryButtonStyle())

                if store.state.delayOff > 0 {
                    Text("Timer aktif: \(store.state.delayOff) menit tersisa")
                        .font(.caption)
                        .foregroundStyle(Theme.muted)
                }
            }
            .disabled(!store.isConnected)
            .opacity(store.isConnected ? 1 : 0.5)

            Card("Catatan", subtitle: "Music mode belum ada di versi iOS") {
                Text(
                    "Desktop GUI punya music mode (streaming UDP). Di iPhone fitur itu butuh listener UDP khusus dan belum diporting; kontrol, scene, flow, dan timer tetap berjalan normal."
                )
                .font(.caption)
                .foregroundStyle(Theme.muted)
            }
        }
    }
}
