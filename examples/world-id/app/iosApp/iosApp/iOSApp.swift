import ComposeApp
import SwiftUI

@main
struct iOSApp: App {
    @Environment(\.scenePhase) private var scenePhase

    var body: some Scene {
        WindowGroup {
            ContentView()
                // World ID return_to = enconomy://worldid; the link only brings the app forward
                .onOpenURL { url in MainViewControllerKt.onOpenUrl(url: url.absoluteString) }
        }
        .onChange(of: scenePhase) { phase in
            if phase == .active { MainViewControllerKt.onOpenUrl(url: nil) }
        }
    }
}
