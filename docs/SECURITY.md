# Security notes

## Local API access

The API has no authentication or role checks. Any process or person that can reach the configured API port can read and modify data, start generation/evaluation jobs, and export datasets. Keep the development server bound to localhost and do not expose it to a network or public interface.

The users table, if present in an existing SQLite database, is legacy data and is no longer read by the application. It is left in place so removing authentication does not delete existing database contents.

## Benchmark confidentiality

Public tasks expose only public test inputs. Evaluation, failure, weakness, validation, and export responses use allowlists. Full target response, hidden test outcomes, expected values, and internal validation evidence remain in SQLite. Public JSONL export excludes solutions, hidden cases, expected outputs, and metadata. Internal export must not be sent to the target model or distributed publicly.

## Candidate execution: unsafe development mode

`EXECUTION_BACKEND=unsafe_subprocess` is the only implemented backend and is explicitly reported as insecure. The subprocess has a temporary current directory, a small environment allowlist, a wall timeout, output checking, and a static AST check. These measures are defense in depth only.

The runner does **not** currently provide:

- Restricted Windows identity or AppContainer isolation
- Filesystem ACL confinement or home/database denial
- Network denial
- Memory, CPU quota, process-count, or file-size limits
- Reliable process-tree cleanup
- Protection against Python introspection/static-check bypasses

Therefore do not execute untrusted code. A secure backend requires a separately reviewed Windows isolation design and adversarial verification. Selecting an unknown backend fails closed rather than falling back to subprocess execution.

## Other limitations

- Rate limiting is in-process and resets on restart.
- CORS is limited to the local Vite origin; CORS does not prevent direct API access.
- The development server should bind to localhost. Do not expose it through a public interface or reverse proxy.
- Detailed error messages are logged server-side; API errors return generic messages and error categories.