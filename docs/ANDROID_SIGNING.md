# Android release signing (CI)

GitHub release APKs are signed with **one fixed release keystore** so users can
**update in place without losing data**. (Debug builds are signed with an ephemeral
per-machine key — Android then refuses the in-place update and the user must
uninstall, which wipes the app-private database. Consistent signing is what makes
"download the new APK and install over the old one" preserve sessions/settings.)

> **The keystore is the app's permanent identity. If you lose it you can never
> ship an update that installs over an existing install again.** Back it up
> (offline + password manager). Do not commit it.

## One-time setup

1. Generate the keystore (keep the file and passwords safe):

   ```bash
   keytool -genkeypair -v \
     -keystore eeg-release.keystore -alias eeg \
     -keyalg RSA -keysize 2048 -validity 10000
   ```

2. Set the four GitHub Actions secrets (run from the repo):

   ```bash
   base64 -w0 eeg-release.keystore | gh secret set ANDROID_KEYSTORE_BASE64
   gh secret set ANDROID_KEYSTORE_PASSWORD   # the keystore password
   gh secret set ANDROID_KEY_ALIAS           # eeg
   gh secret set ANDROID_KEY_PASSWORD        # the key password
   ```

The release workflow (`.github/workflows/release.yml`) decodes the keystore from
`ANDROID_KEYSTORE_BASE64`, exports the `P4A_RELEASE_*` variables, and runs
`buildozer android release` → a signed APK. Without the secrets it falls back to a
debug build and emits a warning (not update-safe).

## Notes

- `buildozer.spec` sets `android.release_artifact = apk` for GitHub/sideload. For a
  Google Play upload, switch it to `aab` and use the same keystore as the **upload
  key** (enroll in Play App Signing on first upload).
- The **first** release-signed build is itself a signature change vs. any
  debug-signed build already installed (e.g. 1.2/1.3 from earlier CI), so that one
  update still forces an uninstall. Every release after it updates in place.
