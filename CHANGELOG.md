# CHANGELOG

<!-- version list -->

## v1.4.1 (2026-08-10)

### Bug Fixes

- **galaxy**: Add role READMEs so the collection imports
  ([`b440894`](https://github.com/matonb/step/commit/b440894030d292d5dac8d9cac091aa3b361f03b0))


## v1.4.0 (2026-08-10)

### Documentation

- **requirements**: State the managed node Python floor as 3.9
  ([#53](https://github.com/matonb/step/pull/53),
  [`0c3bc96`](https://github.com/matonb/step/commit/0c3bc96d8eeedd881ce8e3d2f37972aa1e905f0f))

### Features

- **release**: Publish the collection to Ansible Galaxy
  ([`77395ef`](https://github.com/matonb/step/commit/77395efb0a6394f27f14245ac59b144c00e7e87c))

### Testing

- **unit**: Lift run_module into a conftest fixture ([#54](https://github.com/matonb/step/pull/54),
  [`3e30bf8`](https://github.com/matonb/step/commit/3e30bf83873c2688a41e2c451b2b49a1759935bc))


## v1.3.3 (2026-08-09)

### Bug Fixes

- **tests**: Give root a read bit on /etc/shadow in the redhat image
  ([#52](https://github.com/matonb/step/pull/52),
  [`0fb267b`](https://github.com/matonb/step/commit/0fb267b5a3f5af069a4c1bdf5618ad74420fdbef))

### Testing

- **integration**: Merge connection options via YAML anchor
  ([`d34fef7`](https://github.com/matonb/step/commit/d34fef7d3e4de9cbc4b42863a5405f9227f5ece7))


## v1.3.2 (2026-08-09)

### Bug Fixes

- **tests**: Run the config CA as the user running the suite
  ([`7f476dc`](https://github.com/matonb/step/commit/7f476dc90a1edf7d99286374cdd45adfa1e9bccf))

- **tests**: Stop role.sh hiding every other collection
  ([`7e013ae`](https://github.com/matonb/step/commit/7e013ae2db3fe7262f56792aa467eac5665cf291))

### Continuous Integration

- **workflow**: Install community.general for the role suite
  ([`6a06a54`](https://github.com/matonb/step/commit/6a06a546ea646eec845b7eccc615e1a0c187008b))

- **workflow**: Run the integration suites on a label and on demand
  ([`da94f7d`](https://github.com/matonb/step/commit/da94f7d080ee8bdb6c3f16b65f5f26d98d28614a))

- **workflow**: Test the floor of the supported range too
  ([`4860616`](https://github.com/matonb/step/commit/486061654eee8480f012f4289ceba3a93a16c80f))


## v1.3.1 (2026-08-08)

### Bug Fixes

- **process**: Drop supplementary groups when demoting
  ([`d475dde`](https://github.com/matonb/step/commit/d475ddefb18596fa86b96125967c97f02d154aa2))

- **process**: Install a preexec_fn only when demoting
  ([`d50137c`](https://github.com/matonb/step/commit/d50137cde6029480274ade8a4a72c48cd8349ed1))

- **process**: Resolve the demotion before forking
  ([`326eed4`](https://github.com/matonb/step/commit/326eed46dff84a0e84b80562cd9b789b3a4d060a))

### Continuous Integration

- **pre-commit**: Pin shellcheck to the version CI runs
  ([`98b5bf7`](https://github.com/matonb/step/commit/98b5bf76070641cbb947dab95520f14fe0af684b))

- **workflow**: Pin the sanity runner so shellcheck stays paired
  ([`90c8274`](https://github.com/matonb/step/commit/90c827420c97cd37e9d281b0ed4b262d8a89e3c3))

### Refactoring

- **process**: Delete the unreachable failure handler
  ([`753aba0`](https://github.com/matonb/step/commit/753aba0406508962bd0bd152cfc4ae945bccfebc))

- **process**: Remove the second unreachable handler
  ([`5649305`](https://github.com/matonb/step/commit/564930563853c638831cb36d97629a90e46e164a))

### Testing

- **process**: Assert the demotion hook reaches subprocess
  ([`190bad7`](https://github.com/matonb/step/commit/190bad7c6e19e6f904f2de93c97a09438bae337d))

- **process**: Cover demotion, the timeout path and the helpers
  ([`8dfc9ca`](https://github.com/matonb/step/commit/8dfc9caf160f5f205602fb6a3500d87cdc4509e3))

- **process**: Cover the group lookup failing
  ([`95542a0`](https://github.com/matonb/step/commit/95542a03270100a0ab06818d6f477314442950be))


## v1.3.0 (2026-08-08)

### Bug Fixes

- **ca_server**: Manage the step-ca service lifecycle
  ([`a4b6af6`](https://github.com/matonb/step/commit/a4b6af6d7f460f3d67327e352614dceccc923416))

- **ca_server**: Report on step-ca with an unmanaged repository
  ([`088add6`](https://github.com/matonb/step/commit/088add6ea3c5ee421e12a986daa56c257070f26a))

- **initialize**: Report ok when the CA is already initialized
  ([`45eabcc`](https://github.com/matonb/step/commit/45eabccf9d64f475347bdbcbe377da6d666c2eb9))

- **meta**: Require ansible-core 2.14
  ([`6bbaf01`](https://github.com/matonb/step/commit/6bbaf01eefc0a626c6a7e74d552fd2f5c4b2a86c))

- **step_cli**: Refresh the apt cache when the signing key changes
  ([`10d5547`](https://github.com/matonb/step/commit/10d554707fc063c82725f809214833ac54a3dc2d))

- **step_cli**: Reject either gpg switch on Debian, not just one
  ([`c09e7b4`](https://github.com/matonb/step/commit/c09e7b447bff6614fe7880411675df9868887d42))

- **tests**: Read start_host's family from its argument
  ([`e794317`](https://github.com/matonb/step/commit/e7943172fab644120977325eaf625fbf3277b9f6))

- **tests**: Write both guards as if-then for older shellcheck
  ([`bbdf402`](https://github.com/matonb/step/commit/bbdf40247ddb1a5ead0d16552c057391293a0bb0))

### Chores

- **ca_bootstrap**: Remove the dead systemd unit template
  ([`e7715e0`](https://github.com/matonb/step/commit/e7715e08683e0af157b19a01ffa7d9a7dda1eba5))

### Code Style

- Use American English throughout
  ([`60faeb2`](https://github.com/matonb/step/commit/60faeb25049948547d57c817079c12f5b8dbb025))

- **roles**: Fold the package name scalars
  ([`342edc1`](https://github.com/matonb/step/commit/342edc10964e48dc5ce8ffeaa5d5a4a21f22a2f1))

### Continuous Integration

- **pre-commit**: Run shellcheck locally as CI already does
  ([`8e71e2b`](https://github.com/matonb/step/commit/8e71e2bf913522906f980ac99e293eb709de17ad))

### Documentation

- Describe the collection, its roles and how they are tested
  ([`b3f1bf4`](https://github.com/matonb/step/commit/b3f1bf43650be5d567a9b8ab51b5dda1262b615c))

- **roles**: Say what the gates test and what the defaults are
  ([`a4b5bb2`](https://github.com/matonb/step/commit/a4b5bb2789c2c98caeb39b242a6b72f2ee21fbc5))

- **roles**: Stop describing an unpinned version as latest
  ([`d5d18dc`](https://github.com/matonb/step/commit/d5d18dc760c14234ed85bdfee05eabfc01265aba))

- **step_cli**: Record why check mode differs between the families
  ([`ec2eaf6`](https://github.com/matonb/step/commit/ec2eaf6cacc4bd97443548656298ce9826dcc243))

- **tests**: Renumber the role.sh scenarios its documentation describes
  ([`e931658`](https://github.com/matonb/step/commit/e931658a33893a40087e656547c02cb7e7f31555))

### Features

- **roles**: Define the variables the roles need to run
  ([`f2ce6d7`](https://github.com/matonb/step/commit/f2ce6d7726f24e4bf98d6a117f610505feec307c))

- **roles**: Install from smallstep's package repositories
  ([`aeee7de`](https://github.com/matonb/step/commit/aeee7de2a0e37a155611902917ad4f960993c09c))

### Refactoring

- **ca_server**: Drop the refresh its dependency already does
  ([`8f07c99`](https://github.com/matonb/step/commit/8f07c99d00e67716cd4c4651e03c5a35c79abd2b))

- **ca_server**: Share one version separator, and pin both roles
  ([`384e788`](https://github.com/matonb/step/commit/384e7884c5b34fd06609b9333fc3f69c3f0f1eef))

- **roles**: Derive the repository paths from one name
  ([`f96b9bd`](https://github.com/matonb/step/commit/f96b9bdee3cad02b8fb8a9af3ff57eafea51c3b9))

### Testing

- **roles**: Ask each package manager what it can actually answer
  ([`c57962e`](https://github.com/matonb/step/commit/c57962ee5eb059eefbf5a095e9a5930225974a93))

- **roles**: Assert check mode leaves the repository alone
  ([`c22f10a`](https://github.com/matonb/step/commit/c22f10aa191e43601f2b734f9d9776a12792bb26))

- **roles**: Cover a repository the roles do not manage
  ([`3b1918d`](https://github.com/matonb/step/commit/3b1918dbce63c4d117ea073b6dff2ff74d620b6b))

- **roles**: Drive ca_server against real systemd containers
  ([`8bd12d3`](https://github.com/matonb/step/commit/8bd12d3c97f0f52d46b52581cbf072624fcc95cd))

- **roles**: Exercise version pinning against a real package manager
  ([`895cf6f`](https://github.com/matonb/step/commit/895cf6ffca110189167ae4063a4554d26695d605))

- **roles**: Let the repository assertion reach its own error message
  ([`6563f4b`](https://github.com/matonb/step/commit/6563f4ba39edc75fc47a10c6866648bd07957e9c))

- **roles**: Let the suite say why it could not read the roles
  ([`175bb57`](https://github.com/matonb/step/commit/175bb57ffb8cedeeb011be70f42341c972e9ac03))

- **roles**: Pin RedHat by the version form the docs describe
  ([`15071a3`](https://github.com/matonb/step/commit/15071a3eb0c7efa0ce32c0bc31fbe0c513f3ec66))

- **roles**: Say which failure the pin scenarios expect
  ([`8b50fbf`](https://github.com/matonb/step/commit/8b50fbfd8fc98b0105264246b6354bc2f28ac90e))


## v1.2.0 (2026-08-05)

### Features

- **configure**: Write ca.json atomically via the shared helpers
  ([#45](https://github.com/matonb/step/pull/45),
  [`220b18c`](https://github.com/matonb/step/commit/220b18c21a01b8482b243653df260e0605906d66))


## v1.1.3 (2026-08-05)

### Bug Fixes

- **initialize**: Never delete the CA during a check-mode run
  ([#43](https://github.com/matonb/step/pull/43),
  [`d79bd90`](https://github.com/matonb/step/commit/d79bd906f27f94c5cdff1ea806d025bea24cf7ab))


## v1.1.2 (2026-08-05)

### Bug Fixes

- **configure**: Report changed accurately and declare dependency
  ([#34](https://github.com/matonb/step/pull/34),
  [`61ea949`](https://github.com/matonb/step/commit/61ea949d6db57cc328ceb71e46c378f6c0286f29))


## v1.1.1 (2026-08-05)

### Bug Fixes

- **provisioner**: Read provisioners from ca.json in config mode
  ([#33](https://github.com/matonb/step/pull/33),
  [`083a024`](https://github.com/matonb/step/commit/083a024b708b16e82766df4a6df995cc0045edde))

### Documentation

- **examples**: Add example playbooks for provisioner management
  ([#33](https://github.com/matonb/step/pull/33),
  [`083a024`](https://github.com/matonb/step/commit/083a024b708b16e82766df4a6df995cc0045edde))


## v1.1.0 (2026-08-04)

### Chores

- Replace placeholder collection metadata
  ([`e7f9204`](https://github.com/matonb/step/commit/e7f92042887eadc5c17d3f509ee34524ca0c4452))

### Continuous Integration

- Bump actions to current majors and Node 24
  ([`991cc26`](https://github.com/matonb/step/commit/991cc26d5fbc2321634430d9d3cd22fa3231e41a))

- **lint**: Run ruff and yamllint through pre-commit
  ([`ede111f`](https://github.com/matonb/step/commit/ede111fcd2e709898324d2d565775b5e536414da))

### Features

- **provisioner**: Support step-ca admin mode deployments
  ([`e024d47`](https://github.com/matonb/step/commit/e024d472a3fa22a5e3689b25fdca86956423fe5c))

### Testing

- Add unit and integration suites with CI gating
  ([`283af77`](https://github.com/matonb/step/commit/283af7748ff08c7d5bfc945e0594438f7e02d9cc))


## v1.0.1 (2026-07-29)

### Bug Fixes

- **provisioner**: Honour check mode and allow type-less present
  ([`adcff09`](https://github.com/matonb/step/commit/adcff09295cb50ac86f04dc782728483c9007bc7))

### Code Style

- **docs**: Reformat run_command example in module_utils README
  ([`bdb0f96`](https://github.com/matonb/step/commit/bdb0f96959092c7b903842d0a060f2cf51f794f6))


## v1.0.0 (2026-06-16)

- Initial Release
