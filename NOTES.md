# Notes / gotchas

Technical patterns encountered while building the ISIS underlay (Phase 1) worth
carrying forward into later phases, since some recur.

## SR Linux: independent enable layers

Several features require enabling at multiple layers that don't imply each other --
setting one and assuming the others follow silently fails without error, until the
final commit surfaces it (or doesn't, and the feature just stays down):

- Subinterface existence: `set / interface ethernet-1/1 subinterface 0 type routed`
  must exist before anything else references it -- setting admin-state on a
  not-yet-created subinterface index is accepted into the candidate diff but fails
  at commit once something else tries to resolve it.
- Subinterface admin-state (separate from the base interface's own admin-state).
- IPv4 protocol admin-state on the subinterface (`... subinterface 0 ipv4
  admin-state enable`) -- separate from both the subinterface's admin-state and
  the address object itself. An address can be present and correct while this
  layer is still disabled, and `show interface` will report `no-ip-config` in a
  way that looks like the address is missing when it isn't -- check
  `info from state interface ... subinterface 0` for the full tree if this happens.
- Network-instance binding: referencing a subinterface from `protocols isis
  instance ISIS interface ...` does not add it to the network-instance's interface
  list. That's `set / network-instance default interface <name>.<idx>`, a separate
  explicit step -- confirm with `show network-instance default interfaces *`.
- ISIS per-interface `ipv4-unicast admin-state enable` -- the interface-level
  child needs its own explicit admin-state, distinct from the global ISIS instance
  `ipv4-unicast admin-state enable`.

General takeaway: when something looks correctly configured but isn't functioning,
check one layer down in the tree before assuming the config itself is wrong.
`info from state interface ...` (full state tree) is more reliable than `show
interface` (summary) for catching this class of gap.

## containerlab exec + SR Linux CLI

`containerlab exec --cmd "show ..."` fails -- `show` isn't a shell binary, it's a
mode inside SR Linux's CLI shell. Wrap it:
```
containerlab exec -t topology.clab.yml --cmd 'sr_cli "show interface ethernet-1/1"'
```
Note the nested quoting: outer single quotes for the shell, inner double quotes so
`sr_cli` receives the multi-word command as one argument. Runs the same command
across all nodes in one call, labeled per-node in output.

## Config capture / reproducibility

`clab-<labname>/<node>/config/config.json` reflects committed running config and
is what to copy into a tracked `startup-configs/` directory, referenced from the
topology YAML's `startup-config:` field per node. `checkpoint-0.json` in the same
directory is the factory-default checkpoint Containerlab creates on first deploy --
not current state, don't confuse the two.

`aaamgr_local_user.json` in that same directory holds credential material --
excluded explicitly in `.gitignore`, not just via the blanket `clab-*/` rule.

Validate any capture by destroy + redeploy + re-check state, not by assuming the
copy worked.

## Architecture verification habit

Any new image pulled (not just the first one) gets:
```
docker image inspect <image> -f '{{.Architecture}}'
```
arm64 host, arm64 images only -- a wrong pull silently reintroduces emulation.

## Open item carried into Phase 2

SR-MPLS node SID advertisement into ISIS: configured via a network-instance-level
protocol-independent `local-prefix-sid` (not inside the ISIS instance block
directly). Unconfirmed whether SR-ISIS TLV advertisement to neighbors follows
automatically from this path, or needs an explicit toggle inside the ISIS instance
itself -- verify via adjacency/LSDB inspection before assuming either way.
