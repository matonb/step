# Step CA Provisioner

An Ansible module for managing provisioners in a [Step CA](https://smallstep.com/docs/step-ca) server.

## Description

This module allows you to create, remove, and filter provisioners within a Step CA environment. It provides support for configuring X509 certificate duration parameters and handles service restart requirements when changes are made.

## Requirements

- Ansible 2.9 or higher
- Step CA installed on the target host
- Appropriate permissions to manage Step CA

## Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `name` | string | yes | | Name of the provisioner to manage |
| `state` | string | no | `present` | Desired state: `present` or `absent` |
| `type` | string | no | | Type of provisioner (required when creating a new provisioner) |
| `ca_path` | path | no | | Optional path to the step CA configuration directory (sets STEPPATH) |
| `ca_root` | path | no | | Optional path to the CA root certificate |
| `ca_url` | string | no | | Optional URL of the step CA |
| `fingerprint` | string | no | | Optional fingerprint for CA root |
| `run_as` | string | no | | System user to run Step CLI commands as (typically should be set to `step` for proper access to the CA) |
| `x509_min_dur` | string | no | `20m` | Minimum certificate duration for X509 certificates |
| `x509_max_dur` | string | no | `72h` | Maximum certificate duration for X509 certificates |
| `x509_default_dur` | string | no | `36h` | Default certificate duration for X509 certificates |
| `debug` | boolean | no | `false` | If true, prints CLI commands before execution |

### Provisioner Types

The module supports the following provisioner types:

- `JWK`
- `OIDC`
- `AWS`
- `GCP`
- `Azure`
- `ACME`
- `X5C`
- `K8SSA`
- `SSHPOP`
- `SCEP`
- `Nebula`

### Duration Format

X509 duration parameters accept time units as follows:
- `s` - seconds
- `m` - minutes
- `h` - hours

## Return Values

| Key | Type | Description |
|-----|------|-------------|
| `changed` | boolean | Whether any changes were made |
| `restart_required` | boolean | Indicates if the step-ca service needs to be restarted for changes to take effect |
| `name` | string | The name of the provisioner being managed |
| `provisioners` | list | List of provisioners that matched the specified name and (optional) type |
| `state` | string | The desired state as requested |
| `type` | string | The type of the provisioner (if provided as a filter) |

## Examples

### Create a new JWK provisioner

```yaml
- name: Create JWK provisioner
  matonb.step.provisioner:
    name: my-jwk-provisioner
    type: JWK
    state: present
    run_as: step  # Run as step user for proper CA access
    x509_min_dur: 30m
    x509_max_dur: 48h
    x509_default_dur: 24h
  become: true  # Required when using run_as
  register: provisioner_result
  
- name: Restart step-ca service if needed
  ansible.builtin.service:
    name: step-ca
    state: restarted
  become: true
  when: provisioner_result.restart_required | bool
```

### Remove a provisioner

```yaml
- name: Remove provisioner
  matonb.step.provisioner:
    name: old-provisioner
    state: absent
    run_as: step
  become: true  # Required when using run_as
  register: provisioner_result
  
- name: Restart step-ca service if needed
  ansible.builtin.service:
    name: step-ca
    state: restarted
  become: true
  when: provisioner_result.restart_required | bool
```

### Check if a provisioner exists

```yaml
- name: Check if provisioner exists
  matonb.step.provisioner:
    name: my-provisioner
    run_as: step
  become: true  # Required when using run_as
  register: provisioner_check
  
- name: Display result
  ansible.builtin.debug:
    msg: "Provisioner {{ 'exists' if provisioner_check.provisioners else 'does not exist' }}"
```

### Specifying an alternate path

```yaml
- name: Create provisioner with specific CA path
  matonb.step.provisioner:
    name: new-provisioner
    type: JWK
    run_as: step
    ca_path: /etc/step-ca
    x509_min_dur: 15m
    x509_max_dur: 96h
  become: true  # Required when using run_as
  register: provisioner_result
  
- name: Restart step-ca service if needed
  ansible.builtin.service:
    name: step-ca
    state: restarted
  become: true
  when: provisioner_result.restart_required | bool
```

## Special Notes

- **Important**: The module should typically be run as the `step` user (using `run_as: step`) to ensure proper access to the CA configuration and keys. When using `run_as`, you must also set `become: true` on the task.
- When a provisioner is added or removed, changes are not visible in the Step CA environment until the service is restarted. The module provides a `restart_required` return value to indicate when this is necessary.
- The `type` parameter is required when creating a new provisioner (`state=present`) but is optional when checking for existence or removing a provisioner.
- X509 duration parameters allow you to control the validity periods of certificates issued by the provisioner.

## License

MIT

## Author Information

Brett Maton (@matonb)