// SPDX-License-Identifier: MIT
// The UI test needs a host application; the test drives Andarium instead.
import SwiftUI

@main
struct SoakHostApp: App {
    var body: some Scene {
        WindowGroup { Text("Soak host") }
    }
}
