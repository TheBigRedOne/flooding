# Release Notes

## Version 24.07

The build dependencies have been increased as follows:

- GCC >= 9.3 or Clang >= 7.0 are strongly recommended on Linux; GCC 8.x is also known
  to work but is not officially supported
- Xcode 13 or later is recommended on macOS; older versions may still work but are not
  officially supported
- Boost >= 1.71.0 is required on all platforms

docker:

- Added an official Dockerfile to the repository
- A prebuilt image for *linux/amd64* and *linux/arm64* platforms is available on the
  [GitHub container registry](https://github.com/named-data/ndn-tools/pkgs/container/ndn-tools)

build system:

- Fix detection of libpcap 1.10.2 and later on Linux
- Fix building the man pages with Python 3.12
  ([#5298](https://redmine.named-data.net/issues/5298))
- Reduce amount of debugging information produced in compiled binaries by default
  ([#5279](https://redmine.named-data.net/issues/5279))
- Upgrade `waf` to version 2.0.27

## Version 22.12

The minimum build requirements have been increased as follows:

- Either GCC >= 7.4.0 or Clang >= 6.0 is required on Linux
- On macOS, Xcode 11.3 or later is recommended; older versions may still work but are
  not officially supported
- Boost >= 1.65.1 is required on all platforms
- Sphinx 4.0 or later is required to build the manual pages

chunks:

- Avoid excess window decrease in certain conditions
  ([#5202](https://redmine.named-data.net/issues/5202))
- Use ndn-cxx's `Segmenter` class
  ([#4702](https://redmine.named-data.net/issues/4702))

dissect:

- Recognize several TLV elements that appear in `Certificate` and `SafeBag`
- Remove support for obsolete TLV types

dissect-wireshark:

- Expose `type`, `len`, and `bin` fields

build system:

- Switch to C++17
- macOS 12 (Monterey) and 13 (Ventura) running on arm64 are now supported out-of-the-box
  ([#5135](https://redmine.named-data.net/issues/5135))
- CentOS Stream 9 is now supported; CentOS 8 has been dropped
  ([#5181](https://redmine.named-data.net/issues/5181))
- Stop using the `gold` linker on Linux; prefer instead linking with `lld` if installed
- Upgrade `waf` to version 2.0.24

## Version 22.02

Starting with this release, ndn-tools switched to a date-based versioning scheme:
`YEAR.MONTH[.PATCH]` (`YY.0M[.MICRO]` in [CalVer](https://calver.org/) notation).

chunks:

- Add `--naming-convention` command-line option (Issue #5109)
- Increase the default segment size to 8000 bytes

dissect:

- Support `InterestSignature` fields and more types of name components
- The `Content` field is no longer dissected by default; use the new `--content` option
  to enable it
- Minor cosmetic improvements to the tool output

dissect-wireshark:

- Remove support for obsolete TLV elements
- Recognize `ForwardingHint` (Issue #4185)
- Recognize `ParametersSha256DigestComponent`
- Fix decoding of several TLV elements such as `HopLimit` and `PitToken`
- Update the TLV type of `IncomingFaceId` (Issue #5185)

peek:

- Replace `--link-file` option with `--fwhint` and adapt to the new `ForwardingHint`
  format (Issues #4207, #5187)

poke:

- Remove deprecated `--force` option; use `--unsolicited` instead
- Remove deprecated `--identity` and `--digest` options; use `--signing-info` instead
- Change the short form of `--freshness` to `-f`

pingserver:

- Remove deprecated `-x` alias for the `--freshness` option

build system:

- Upgrade `waf` to version 2.0.23

## Version 0.7.1

The build requirements have been increased to require Clang >= 4.0, Xcode >= 9.0, and Python >= 3.6.
Meanwhile, it is *recommended* to use GCC >= 7.4.0 and Boost >= 1.65.1.

This release contains minor build fixes and code cleanups.

## Version 0.7

chunks:

- Add `--no-version-discovery` option to ndncatchunks (Issue #5021)
- Improve CUBIC performance on lossy networks (Issue #5036)
- Switch to ndn-cxx's `RttEstimatorWithStats` class (Issue #4887)
- Remove previously deprecated options `-d` and `-t` from ndncatchunks

ping:

- Change the short form of ndnpingserver's `--freshness` option to `-f`,
  for consistency with ndnputchunks

peek:

- Add `--app-params`, `--app-params-file`, and `--hop-limit` options
- The `--link-file` option now expects a raw binary file
- Print Data name and Nack reason if `--verbose` is specified
- Code cleanup
- Manual page improvements

poke:

- Add `--signing-info` option, replacing `--digest` and `--identity` which are
  now deprecated
- Add `--verbose` option
- Wait indefinitely if `--timeout` is not specified
- The program now exits with status 3 when a timeout occurs and with status 5
  if prefix registration fails
- Rename `--force` option to `--unsolicited`
- Code cleanup
- Major rewrite of the manual page

## Version 0.6.4

chunks:

- Add metadata-based version discovery and remove iterative discovery (Issue #4556)
- Remove manual selection of version discovery method via `-d` option (Issue #4832)
- Implement CUBIC congestion window adaptation in ndncatchunks (Issue #4861)
- Increase the default retransmission limit from 3 to 15 (Issue #4861)
- Improve stats printed by ndncatchunks after transfer completes (Issue #4603)
- Add manual page for ndnputchunks

dissect & dissect-wireshark:

- Follow packet specification changes to renumber the `Parameters` element and
  rename it to `ApplicationParameters` (Issues #4658, #4780)

dump:

- Fix compilation on CentOS 7 (Issue #4852)

pib:

- Completely remove this obsolete and unmaintained tool (Issue #4205)

## Version 0.6.3

chunks:

- Fix impossible RTT values (Issue #4604)
- Add support for RDR metadata in ndnputchunks (Issue #4556)
- Use `PendingInterestHandle` and `RegisteredPrefixHandle` (Issues #4316, #3919)

ping:

- Add systemd unit file for ndnpingserver (Issue #4594)
- Use `PendingInterestHandle` and `RegisteredPrefixHandle` (Issues #4316, #3919)

poke:

- Use `PendingInterestHandle` and `RegisteredPrefixHandle` (Issues #4316, #3919)

build system:

- Upgrade `waf` to version 2.0.14 and other improvements

## Version 0.6.2

The build requirements have been upgraded to gcc >= 5.3 or clang >= 3.6, boost >= 1.58,
openssl >= 1.0.2. This effectively drops support for all versions of Ubuntu older than 16.04
that use distribution-provided compilers and packages.

The compilation now uses the C++14 standard.

chunks:

- Fix AIMD hanging with files smaller than the chunk size (Issue #4439)

dissect-wireshark:

- Show `Name` and `FinalBlockId` as URIs (Issue #3106)
- Improve NDNLPv2 support (Issue #4463)
- Add support for dissecting PPP frames

dump:

- Remove dependency on Boost.Regex
- Stop using tcpdump headers files
- Compile pcap filter with optimizations enabled
- Capture in promiscuous mode by default, add an option to disable it
- Add `-t` option to suppress printing per-packet timestamp
- Properly handle exceptions thrown by `lp::Packet::wireDecode()` (Issue #3943)
- Add UDP port 56363 to the default pcap filter
- Stricter parsing of IP/TCP/UDP headers
- Add IPv6 support
- Code cleanup

poke:

- Use `Face::unsetInterestFilter` instead of `shutdown` (Issue #4642)
- Improve unit testing (Issue #3740)

ping:

- Add `--quiet` option to ndnpingserver (Issue #4673)
- Set `CanBePrefix=false` in Interests sent by ndnping (Issue #4581)
- Code cleanup

## Version 0.6.1

chunks:

- Show correct packet loss stats in final summary (Issue #4437)
- Avoid printing meaningless values when no RTT measurements are available (Issue #4551)

dissect:

- Recognize `CanBePrefix`, `HopLimit`, and `Parameters` TLV elements (Issue #4590)

dissect-wireshark:

- Recognize `CanBePrefix`, `HopLimit`, and `Parameters` TLV elements (Issue #4517)

peek:

- Drop `Selectors` support (Issue #4571)
- Add `-P/--prefix` option to set `CanBePrefix` in the Interest packet

build system:

- Upgrade `waf` to version 2.0.6 and other improvements

## Version 0.6

chunks:

- Change the default Interest pipeline to AIMD (Issue #4402)
- Include RTT stats in final summary (Issue #4406)
- Respect `--retries=-1` in the AIMD pipeline (Issue #4409)
- React to congestion marks by default as a timeout event (can be disabled using
  `--aimd-ignore-cong-marks`) (Issue #4289)
- Print a final summary of the transfer regardless of the pipeline type, and even if
  `--verbose` was not specified (Issue #4421)

## Version 0.5

all:

- Switch to version 2 of certificates, `KeyChain`, and `Validator` (Issue #4089)
- Compilation fixes (Issue #4259)

chunks:

- Make `ndnputchunks` display some output by default; a new `-q` flag makes the tool
  completely silent, except for errors (Issue #4286)
- Refactor `ndnputchunks` options handling
- Reduce initial timeout of iterative version discovery in `ndncatchunks` (Issue #4291)
- Fix potential `ndncatchunks` crash on exit

peek:

- Convert use of `Link` into `ForwardingHint` (Issue #4055)

## Version 0.4

As of this version, NDN Essential Tools require a modern compiler (gcc >= 4.8.2, clang >= 3.4)
and a relatively new version of the Boost libraries (>= 1.54).  This means that the code no
longer compiles with the packaged version of gcc and Boost libraries on Ubuntu 12.04.
NDN Essential Tools can still be compiled on such systems, but require a separate
installation of a newer version of the compiler (e.g., clang-3.4) and dependencies.

chunks:

- Change default version discovery to iterative
- Improve help text of `ndnputchunks`
- Fix `DiscoverVersionIterative` build error
- Modularize Interest pipeline implementation
- Add AIMD congestion control (Issue #3636)
- Code cleanup and improvements

dissect-wireshark:

- Add initial support for NDNLPv2 (Issue #3197)
- Fix potential memory overflow

dump:

- Add support for Linux cooked-mode capture (SLL) (Issue #3061)
- Improve error messages

pib:

- Disable by default (can be compiled with ndn-cxx version 0.5.0)
- Fix compilation error with new version of ndn-cxx library
- Avoid use of deprecated block helpers
- Correct build target path

ping:

- Recognize and trace NACK
- Fix potential divide-by-zero bug in `StatisticsCollector` (Issue #3504)

peek:

- Recognize and properly handle NACK
- Refactor implementation

## Version 0.3

chunks: **New** (pair of) tool(s) for segmented file transfer

peek:

- Allow verbose output
- Switch from `getopt` to `boost::program_options`
- Add `--link-file` option

ping:

- Document ndnping protocol

dump:

- Capture and print network NACK packets
- Update docs to include NACK capture feature

build system:

- Enable `-Wextra` by default
- Fix missing tool name in `configure --help` output
- Fix compatibility with Python 3

## Version 0.2

Code improvements and two new tools:

- PIB service to manage the public information of keys and publish certificates
  (Issue 3018)
- A Wireshark dissector for NDN packets (Issue 3092)

## Version 0.1

Initial release of NDN Essential Tools, featuring:

- ndnpeek, ndnpoke: a pair of programs to request and make available for
  retrieval a single Data packet.
- ndnping, ndnpingserver: reachability testing tools for Named Data Networking.
- ndndump: a traffic analysis tool that captures NDN packets on the wire.
- ndn-dissect: an NDN packet format inspector. It reads zero or more NDN
  packets from either an input file or the standard input, and displays the
  Type-Length-Value (TLV) structure of those packets on the standard output.
