# `run_command` Function Reference

## Overview

The `run_command` function in `plugins/module_utils/process.py` provides a unified way to execute shell commands in Ansible modules with advanced features:

- User impersonation (run as a different system user)
- Timeout handling with real-time output capture
- Environment variable control
- Comprehensive error handling

## Function Signature

```python
def run_command(
    command: Union[List[str], str],
    debug: bool = False,
    env_vars: Optional[Dict[str, str]] = None,
    shell: bool = False,
    username: Optional[str] = None,
    timeout: Optional[float] = None,
    check: bool = True,
    text: bool = True,
) -> subprocess.CompletedProcess:
```

## Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `command` | `List[str]` or `str` | Required | The command to execute as either a list of arguments or a string |
| `debug` | `bool` | `False` | If `True`, prints the command before execution |
| `env_vars` | `Dict[str, str]` | `None` | Additional environment variables for the command |
| `shell` | `bool` | `False` | Whether to run the command through a shell |
| `username` | `str` | `None` | System user to run the command as (requires root privileges) |
| `timeout` | `float` | `None` | Maximum time in seconds to wait for the command to complete |
| `check` | `bool` | `True` | If `True`, raises an exception when the command returns a non-zero exit code |
| `text` | `bool` | `True` | If `True`, decodes stdout and stderr as text instead of bytes |

## Return Value

Returns a `subprocess.CompletedProcess` object with the following attributes:
- `args`: The command arguments
- `returncode`: The exit code
- `stdout`: The standard output (as text if `text=True`, or bytes otherwise)
- `stderr`: The standard error (as text if `text=True`, or bytes otherwise)

## Exceptions

- `RuntimeError`: Raised if:
  - User switching fails
  - The command returns a non-zero exit code (if `check=True`)
- `CommandTimeout`: Raised if the command exceeds the specified timeout

## Usage Examples

### Basic Usage

```python
result = run_command(["ls", "-la"])
print(f"Exit code: {result.returncode}")
print(f"Output: {result.stdout}")
```

### With Timeout

```python
try:
    result = run_command(["sleep", "10"], timeout=5)
except CommandTimeout as exc:
    print(f"Command timed out: {exc}")
    print(f"Partial stdout: {exc.stdout}")
```

### Running as Another User

```python
# Requires root privileges
result = run_command(
    ["whoami"], 
    username="otheruser", 
    env_vars={"CUSTOM_VAR": "value"}
)
```

### Shell Command with Non-zero Exit Handling

```python
try:
    result = run_command("grep pattern file.txt || echo 'Not found'", shell=True)
except RuntimeError as exc:
    print(f"Command failed: {exc}")
```

## Backward Compatibility

For backward compatibility, the function is also available with its old name:

```python
# These two calls are equivalent
result1 = run_command(command, username="user")
result2 = run_command_as_user(command, username="user")
```