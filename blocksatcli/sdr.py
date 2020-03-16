"""SDR Receiver Wrapper"""
from argparse import ArgumentDefaultsHelpFormatter
from . import config, defs, util
import subprocess, logging, textwrap
logger = logging.getLogger(__name__)


def _tune_max_pipe_size(pipesize = (64800*32)):
    """Tune the maximum size of pipes"""
    try:
        subprocess.check_output(["which", "sysctl"])
    except subprocess.CalledProcessError:
        logging.error("Couldn't tune max-pipe-size. Please check how to tune "
                      "it in your OS.")
        return False

    ret = subprocess.check_output(["sysctl", "fs.pipe-max-size"])
    current_max = int(ret.decode().split()[-1])

    if (current_max < pipesize):
        cmd = ["sudo", "sysctl", "-w", "fs.pipe-max-size=" + str(pipesize)]

        print(textwrap.fill("The maximum pipe size that is currently "
                            "configured in your OS is of {} bytes, which is "
                            "not sufficient for the demodulator application. "
                            "It will be necessary to run the following command "
                            "as root:".format(current_max), width=80))
        print("\n" + " ".join(cmd) + "\n")

        if (not util._ask_yes_or_no("Is that OK?", default="y")):
            print("Abort")
            return False

        return subprocess.check_output(cmd)
    else:
        return True


def _check_apps():
    """Check if required apps are installed"""
    try:
        subprocess.check_output(["which", "rtl_sdr"])
    except subprocess.CalledProcessError:
        logging.error("Couldn't find rtl_sdr. Is it installed?")
        return False

    try:
        subprocess.check_output(["which", "leandvb"])
    except subprocess.CalledProcessError:
        logging.error("Couldn't find leandvb. Is it installed?")
        return False

    try:
        subprocess.check_output(["which", "ldpc_tool"])
    except subprocess.CalledProcessError:
        logging.error("Couldn't find ldpc_tool. Is it installed?")
        return False

    try:
        subprocess.check_output(["which", "tsp"])
    except subprocess.CalledProcessError:
        logging.error("Couldn't find tsp. Is it installed?")
        return False

    return True


def subparser(subparsers):
    """Parser for sdr command"""
    p = subparsers.add_parser('sdr',
                              description="Launch SDR receiver",
                              help='Launch SDR receiver',
                              formatter_class=ArgumentDefaultsHelpFormatter)

    rtl_p = p.add_argument_group('rtl_sdr options')
    rtl_p.add_argument('--derotate', default=0, type=float,
                       help='Frequency offset correction to apply in kHz')
    rtl_group = rtl_p.add_mutually_exclusive_group()
    rtl_group.add_argument('-g', '--gain', default=30, type=float,
                           help='RTL-SDR Rx gain')
    rtl_group.add_argument('-f', '--iq-file', default=None,
                           help='File to read IQ samples from instead of reading '
                           'from the RTL-SDR in real-time')

    ldvb_p = p.add_argument_group('leandvb options')
    ldvb_p.add_argument('-n', '--n-helpers', default=6, type=int,
                        help='Number of LDPC decoding threads')
    ldvb_p.add_argument('-d', '--debug-ts', action='count', default=0,
                        help="Activate debugging on leandvb. Use it multiple "
                        "times to increase the debugging level.")
    ldvb_p.add_argument('-v', '--verbose', default=False, action='store_true',
                        help='leandvb in verbose mode')
    ldvb_p.add_argument('--gui', default=False, action='store_true',
                        help='GUI mode')
    ldvb_p.add_argument('--fastlock', default=False, action='store_true',
                        help='leandvb fast lock mode')
    ldvb_p.add_argument('--rrc-rej', default=30, type=int,
                        help='leandvb RRC rej parameter')
    ldvb_p.add_argument('-m', '--modcod', default="low",
                        choices=["low", "high"],
                        help="Choose low-throughput vs high-throughput MODCOD")
    ldvb_p.add_argument('--ldpc-tool', default="/usr/local/bin/ldpc_tool",
                        help='Path to ldpc_tool')

    tsp_p = p.add_argument_group('tsduck options')
    tsp_p.add_argument('--buffer-size-mb', default=1.0, type=float,
                       help='Input buffer size in MB')
    tsp_p.add_argument('--max-flushed-packets', default=10, type=int,
                       help='Maximum number of packets processed by a tsp '
                       'processor')
    tsp_p.add_argument('--max-input-packets', default=10, type=int,
                       help='Maximum number of packets received at a time from '
                       'the tsp input plugin ')
    tsp_p.add_argument('-p', '--bitrate-period', default=5, type=int,
                       help='Period of bitrate reports in seconds')
    tsp_p.add_argument('-l', '--local-address', default="127.0.0.1",
                       help='IP address of the local interface on which to '
                       'listen for UDP datagrams')
    tsp_p.add_argument('-a', '--analyze', default=False, action='store_true',
                       help='Analyze transport stream and save report on '
                       'program termination')
    tsp_p.add_argument('--analyze-file', default="ts-analysis.txt",
                       action='store_true',
                       help='File on which to save the MPEG-TS analysis.')
    tsp_p.add_argument('--no-monitoring', default=False, action='store_true',
                       help='Disable bitrate and MPEG-TS discontinuity '
                       'monitoring')

    p.set_defaults(func=run,
                   record=False)

    subsubparsers = p.add_subparsers(title='subcommands',
                                     help='Target SDR sub-command')
    # IQ recording
    p2 = subsubparsers.add_parser('rec',
                                  description="Record IQ samples instead of "
                                  "feeding them into leandvb",
                                  help='Record IQ samples',
                                  formatter_class=ArgumentDefaultsHelpFormatter)
    p2.add_argument('-f', '--iq-file', default="blocksat.iq",
                    help='File on which to save IQ samples received with '
                    'the RTL-SDR.')
    p2.set_defaults(record=True)

    return p


def run(args):
    info = config.read_cfg_file()

    if (info is None):
        return

    if (not _tune_max_pipe_size()):
        return

    if (not _check_apps()):
        return

    modcod = defs.low_rate_modcod if args.modcod == "low" else \
             defs.high_rate_modcod

    if (args.iq_file is None or args.record):
        rtl_cmd = ["rtl_sdr", "-g", str(args.gain), "-f",
                   str(info['freqs']['l_band']*1e6), "-s", str(defs.samp_rate)]
        if (args.record):
            print("IQ recording will be saved on file {}".format(
                args.iq_file))
            print(textwrap.fill("NOTE: the file will grow by approximately "
                                "3.8MB per second."))
            if (not util._ask_yes_or_no("Proceed?", default="y")):
                return
            rtl_cmd.append(args.iq_file)
        else:
            rtl_cmd.append("-")

    ldvb_cmd = ["leandvb", "--nhelpers", str(args.n_helpers), "-f",
                str(defs.samp_rate), "--sr", str(defs.sym_rate), "--roll-off",
                str(defs.rolloff), "--standard", "DVB-S2", "--sampler", "rrc",
                "--rrc-rej", str(args.rrc_rej), "--ldpc-helper", args.ldpc_tool,
                "--modcods", modcod]
    if (args.debug_ts == 1):
        ldvb_cmd.append("-d")
    elif (args.debug_ts > 1):
        ldvb_cmd.extend(["-d", "-d"])
    if (args.gui):
        ldvb_cmd.append("--gui")
    if (args.verbose):
        ldvb_cmd.append("-v")
    if (args.fastlock):
        ldvb_cmd.append("--fastlock")
    if (args.derotate != 0.0):
        ldvb_cmd.extend(["--derotate", str(int(args.derotate*1e3))])

    # Input
    tsp_cmd = ["tsp", "--realtime", "--buffer-size-mb",
               str(args.buffer_size_mb), "--max-flushed-packets",
               str(args.max_flushed_packets), "--max-input-packets",
               str(args.max_input_packets)]
    # MPEG-TS Analyzer
    if (args.analyze):
        print("MPEG-TS analysis will be saved on file {}".format(
            args.analyze_file))
        if (not util._ask_yes_or_no("Proceed?", default="y")):
            return
        tsp_cmd.extend(["-P", "analyze", "-o", args.analyze_file])
    if (not args.no_monitoring):
        # Monitor discontinuities
        tsp_cmd.extend(["-P", "continuity"])
        # Monitor Bitrate
        tsp_cmd.extend(["-P", "bitrate_monitor", "-p",
                        str(args.bitrate_period)])
    # MPE plugin
    tsp_cmd.extend(["-P", "mpe", "--pid",
                    "-".join([str(pid) for pid in defs.pids]), "--udp-forward",
                    "--local-address", args.local_address])
    # Output
    tsp_cmd.extend(["-O", "drop"])

    logger.debug("Run:")

    if (args.record):
        p1 = subprocess.Popen(rtl_cmd)
        p1.communicate()
        return
    elif (args.iq_file is None):
        logger.debug("> " + " ".join(rtl_cmd) + " | \\\n" + \
                 " ".join(ldvb_cmd) + " | \\\n" + \
                 " ".join(tsp_cmd))
        p1 = subprocess.Popen(rtl_cmd, stdout=subprocess.PIPE)
        p2 = subprocess.Popen(ldvb_cmd, stdin=p1.stdout, stdout=subprocess.PIPE)
    else:
        logger.debug("> " + " ".join(ldvb_cmd) + " < " + args.iq_file + \
                     " | \\\n" + " ".join(tsp_cmd))
        fd_iq_file = open(args.iq_file)
        p2 = subprocess.Popen(ldvb_cmd, stdin=fd_iq_file,
                              stdout=subprocess.PIPE)
    p3 = subprocess.Popen(tsp_cmd, stdin=p2.stdout)
    p3.communicate()

