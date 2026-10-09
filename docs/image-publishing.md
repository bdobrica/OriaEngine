# Publishing container images

The [release workflow](../.github/workflows/docker-publish.yml) follows
SecondContext's workflow at commit `6f4f4183cb42298ef8850b36b38801950fe4eff5`.
A push to `main` publishes only images whose committed `current_version` increased
over the complete push range.

| Image | Version file | Dockerfile / contents |
| --- | --- | --- |
| `quay.io/bdobrica/oria-engine` | [root version](../.bumpversion.cfg) | [Application](../deploy/Dockerfile): gateway, worker and explicit migrations |
| `quay.io/bdobrica/oria-astrology-mcp` | [service version](../services/astrology_mcp/.bumpversion.cfg) | [Astrology MCP](../services/astrology_mcp/Dockerfile): deterministic calculation service |

Both images use the repository root build context and locked runtime dependencies.
Each release publishes numeric `MAJOR.MINOR.PATCH` and `latest` tags for
`linux/amd64` and `linux/arm64`, with OCI source, commit and image-version labels.
The version is independent of the Python package version in `pyproject.toml` and
`uv.lock`; bumping an image requires no package or lockfile change.

## Registry setup

Create `oria-engine` and `oria-astrology-mcp` repositories in the `bdobrica`
Quay namespace. Give an account or robot write access to both. In GitHub
**Settings → Secrets and variables → Actions**, add the repository secret
`QUAY_AUTH` containing base64-encoded `USERNAME:PASSWORD_OR_ROBOT_TOKEN`.
This is the same `auth` value used in Docker registry configuration; a robot
username can look like `bdobrica+github`. The image namespace remains `bdobrica`
regardless of the login username.

Keep this value in GitHub secrets, outside source, `.env`, commands and chat.
The workflow validates it without printing it, writes a private temporary Docker
authentication file and removes the file even after a failed build. Registry
credentials are not build arguments or application runtime configuration.
Pull requests run release-selection tests without accessing registry credentials.

## Choose a release

From a clean repository root, use the same optional local bump2version tool as
SecondContext; this adds no application dependency:

```sh
uv tool install bump2version==1.0.1

# Application image only:
bump2version --config-file .bumpversion.cfg patch
git add .bumpversion.cfg
git commit -m "build(release): bump application image to 0.1.1"
git push origin main

# Astrology image only, as a separate release:
bump2version --config-file services/astrology_mcp/.bumpversion.cfg patch
git add services/astrology_mcp/.bumpversion.cfg
git commit -m "build(release): bump astrology image to 0.1.1"
git push origin main
```

Use `minor` or `major` instead of `patch` when appropriate. Both configs disable
automatic commits and Git tags, so choose the commit message yourself. Bump both
files and commit/push them together to release both images. Shared source/dependency
changes can affect both images; choose both releases when those changes should ship.

The initial `0.1.0` files establish a baseline and **do not publish images**.
Push that baseline to `main` first, then bump to `0.1.1` for the first publication.
Adding the baseline and bumping it in the same push still establishes only a baseline.
Ordinary edits, version-file comments, added/removed configs, new-branch baselines
and pull requests do not publish. A bump reverted within a push also publishes
nothing. Only the final increased version of each image is built, from the
triggering commit. Malformed numeric versions, downgrades and unavailable baseline
commits fail detection rather than releasing blindly.

## Verification, retries and deployment

`make test-releases` tests selection against disposable Git histories without
Docker, provider keys or application dependencies. It is also included in
`make verify` and run by the publishing workflow. The existing application
verification workflow runs independently; publication is not gated on its result.
Run `make verify` before choosing a release and check the Verify workflow.

Image builds use QEMU/Buildx, separate image caches and independent matrix jobs.
GitHub's job summary records tags and the published manifest digest. Retry a failed
publication by rerunning that workflow. `latest` follows the last completed publish,
including reruns of older releases; pin deployments to version tags or digests.

Publishing does not restart services, register webhooks or run database migrations.
The existing [development stack](development.md) continues building local images;
setting `ORIA_APP_IMAGE` changes its local tag and does not switch it to pulling
registry images. Gateway is the application image's default command; worker uses
`python -m oria_engine.queue`, and migration uses `python -m alembic upgrade head`.
An operator deployment must preserve the [private networks and ownership boundaries](architecture.md),
explicit migration ordering, runtime secrets and service-specific health probes.
Resolve the existing [Swiss Ephemeris/binding licensing requirements](astrology-mcp.md#dependency-and-licensing-notes)
before distribution. The [MVP release gate](../TODO.md#stage-25--mvp-release-gate)
remains separate from image publication.
