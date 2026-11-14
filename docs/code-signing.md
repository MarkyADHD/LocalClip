# Code signing

`LocalClip.exe` and `LocalClip-Setup.exe` are signed through [SignPath](https://about.signpath.io) with a certificate from
[SignPath Foundation](https://signpath.org). The policy users see is in the [README](../README.md#code-signing-policy).

## How a release gets signed

The "Desktop app" workflow (`.github/workflows/desktop.yml`), run by hand from `main`:

1. builds `LocalClip.exe` and sends it to SignPath;
2. waits (up to two hours) for an approver to approve the request in SignPath;
3. builds `LocalClip-Setup.exe` around the signed app and sends that to SignPath, which needs a second approval;
4. checks both signatures and publishes the release.

The app is signed first because SignPath can't sign files inside an Inno Setup installer.
The uninstaller Inno Setup generates is not signed.

Signing only runs when the repository variable `SIGNPATH_ORGANIZATION_ID` is set. Pull request builds are never signed.

## SignPath setup

| Where | Name | Value |
|---|---|---|
| GitHub repository variable | `SIGNPATH_ORGANIZATION_ID` | the organization ID from SignPath |
| GitHub repository secret | `SIGNPATH_API_TOKEN` | API token of a SignPath CI user that is a submitter on the signing policy |
| SignPath project | slug | `LocalClip` |
| SignPath signing policy | slug | `release-signing` |
| SignPath trusted build system | | GitHub.com, linked to the project |

Two artifact configurations in the SignPath project. GitHub wraps each uploaded file in a zip, hence `zip-file`.

`exe`:

```xml
<artifact-configuration xmlns="http://signpath.io/artifact-configuration/v1">
  <parameters>
    <parameter name="version" required="true" />
  </parameters>
  <zip-file>
    <pe-file path="LocalClip.exe" product-name="LocalClip" product-version="${version}">
      <authenticode-sign />
    </pe-file>
  </zip-file>
</artifact-configuration>
```

`installer`: the same with `path="LocalClip-Setup.exe"`.
