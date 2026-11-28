# Asterisk Node Manager glossary

Terms specific to the Asterisk Node Manager.

## Terms

### Node

A configured Asterisk node managed by this installation.

_Avoid_: repeater, unless referring specifically to the physical radio system.

### Node Number

The numeric configuration value identifying a managed node in Asterisk
configuration. It is not the registration identity term **Node ID**.

_Avoid_: network-specific node number.

### Live tuning

A temporary change to an Asterisk USB radio driver's runtime tuning values.
Live tuning is not saved to the configuration database and is lost when
Asterisk reloads; save the desired value in the web app to make it persistent.

### Network Profile

A named set of network-specific settings used to generate node configuration.

### Default Network

The installation-wide network profile used by nodes without a per-node
selection, and by every node when advanced per-node selection is disabled.

### Per-node network selection

The optional advanced setting that lets an individual node use a network
profile other than the installation's Default Network.
