#!/usr/bin/env python3
"""
Launch the DVB receiver
"""
import os, sys, signal, argparse, subprocess, re, time, logging, threading, json
from pprint import pformat, pprint
from ipaddress import IPv4Interface
import textwrap


# Constants
src_ports   = ["4433", "4434"]
pids        = [32, 33]
satellites  = [
    {
        'name'    : "Galaxy 18",
        'alias'   : "G18",
        'dl_freq' : 12016.92,
        'band'    : "Ku",
        'pol'     : "H"
    },
    {
        'name'    : "Eutelsat 113",
        'alias'   : "E113",
        'dl_freq' : 12026.15,
        'band'    : "Ku",
        'pol'     : "V"
    },
    {
        'name'    : "Telstar 11N Africa",
        'alias'   : "T11N AFR",
        'dl_freq' : 11476.75,
        'band'    : "Ku",
        'pol'     : "H"
    },
    {
        'name'    : "Telstar 11N Europe",
        'alias'   : "T11N EU",
        'dl_freq' : 11504.02,
        'band'    : "Ku",
        'pol'     : "V"
    },
    {
        'name'    : "Telstar 18V",
        'alias'   : "T18V",
        'dl_freq' : 4057.5,
        'band'    : "C",
        'pol'     : "H"
    },
    {
        'name'    : "Eutelsat 113 - Test carrier",
        'alias'   : "E113",
        'dl_freq' : 12066.9,
        'band'    : "Ku",
        'pol'     : "V"
    }
]

linux_usb_setup_type  = "Linux USB"
sdr_setup_type        = "Software-defined"
standalone_setup_type = "Standalone"

modems = [
    {
        'vendor' : "Novra",
        'model'  : "S400",
        'type'   : standalone_setup_type
    },
    {
        'vendor' : "TBS",
        'model'  : "5927",
        'type'   : linux_usb_setup_type
    },
    {
        'vendor' : "TBS",
        'model'  : "5520SE",
        'type'   : linux_usb_setup_type
    },
    {
        'vendor' : "",
        'model'  : "RTL-SDR",
        'type'   : sdr_setup_type
    }
]

ku_band_thresh = 11700.0

lnbs = [
    {
        'vendor'    : "Avenger",
        'model'     : "PLL321S-2",
        'lo_freq'   : [9750.0, 10600],
        'universal' : True,
        'band'      : "Ku"

    },
    {
        'vendor'    : "Maverick",
        'model'     : "MK1",
        "lo_freq"   : 10750.0,
        'universal' : False,
        'band'      : "Ku"
    },
    {
        'vendor'    : "Titanium",
        'model'     : "C1",
        "lo_freq"   : 5150.0,
        'universal' : False,
        'band'      : "C"
    }
]

v4l_lnbs = [
    {
        'name' : "UNIVERSAL"
    },
    {
        'name' : "DBS"
    },
    {
        'name' : "EXTENDED"
    },
    {
        'name' : "STANDARD"
    },
    {
        'name' : "L10700"
    },
    {
        'name' : "L10750"
    },
    {
        'name' : "L11300"
    },
    {
        'name' : "ENHANCED"
    },
    {
        'name' : "QPH031"
    },
    {
        'name' : "C-BAND"
    },
    {
        'name' : "C-MULT"
    },
    {
        'name' : "DISHPRO"
    },
    {
        'name' : "110BS"
    },
    {
        'name' : "STACKED-BRASILSAT"
    },
    {
        'name' : "OI-BRASILSAT"
    },
    {
        'name' : "AMAZONAS"
    },
    {
        'name' : "GVT-BRASILSAT"
    }
]

lnb_options = [x['name'] for x in v4l_lnbs]

def _ask_yes_or_no(msg, default="y"):
    """Yes or no question

    Args:
        msg     : the message or question to ask the user
        default : default response

    Returns:
        True if answer is yes, False otherwise.

    """
    response = None

    if (default == "y"):
        options = "[Y/n]"
    else:
        options = "[N/y]"

    question = msg + " " + options + " "

    while response not in {"y", "n"}:
        raw_resp = input(question) or default
        response = raw_resp.lower()

        if (response not in {"y", "n"}):
            print("Please enter \"y\" or \"n\"")

    return (response == "y")


def _ask_multiple_choice(vec, msg, label, to_str):
    """Multiple choice question

    Args:
        vec    : Vector with elements to choose from
        msg    : Msg to prompt user for choice
        label  : Description/label of what "vec" holdes
        to_str : Function that prints information about elements

    Returns:
        Chosen element

    """
    assert(len(vec) > 1)

    for i_elem, elem in enumerate(vec):
        elem_str = to_str(elem)
        print("[%2u] %s" %(i_elem, elem_str))

    resp = None
    while (not isinstance(resp, int)):
        try:
            resp = int(input("\n%s number: " %(label)))
        except ValueError:
            print("Please choose a number")
            continue

        if (resp >= len(vec)):
            print("Please choose number from 0 to %u" %(len(vec) - 1))
            resp = None
            continue

        choice = vec[resp]
        print(to_str(choice))
        return choice


def _print_header(header, target_len=80):
    """Print section header"""

    prefix      = ""
    suffix      = ""
    header_len  = len(header) + 2
    remaining   = target_len - header_len
    prefix_len  = int(remaining / 2)
    suffix_len  = int(remaining / 2)

    if (remaining % 1 == 1):
        prefix_len += 1

    for i in range(0, prefix_len):
        prefix += "-"

    for i in range(0, suffix_len):
        suffix += "-"

    print("\n" + prefix + " " + header + " " + suffix)


def _print_sub_header(header, target_len=60):
    """Print sub-section header"""
    _print_header(header, target_len=target_len)


def _read_cfg_file():
    """Read configuration file"""

    cfg_file = "config.json"

    if (os.path.isfile(cfg_file)):
        with open(cfg_file) as fd:
            info = json.load(fd)
        return info


def _cfg_satellite():
    """Configure satellite covering the user"""

    _print_header("Satellite")

    print("Please inform the satellite covering your location")
    print("Not sure? Check the coverage map at:\n" \
          "https://blockstream.com/satellite/#satellite_network-coverage")

    question = "Please, inform which satellite below covers your location:"
    sat = _ask_multiple_choice(satellites,
                               question,
                               "Satellite",
                               lambda sat : '{} ({})'.format(sat['name'],
                                                             sat['alias']))
    return sat


def _cfg_rx_setup():
    """Configure Rx setup - which receiver user is using """

    _print_header("Receiver Setup")

    question = "Please, inform your DVB-S2 receiver setup from the list below:"
    modem = _ask_multiple_choice(modems,
                                 question,
                                 "Setup",
                                 lambda x : '{} receiver, using {} {} modem'.format(
                                     x['type'], x['vendor'], x['model']))
    return modem


def _cfg_custom_lnb(sat):
    """Configure custom LNB based on user-entered specs

    Args:
        sat : user's satellite info

    """

    print("Please inform the specifications of you LNB:")

    print("Frequency band:")
    bands = ["C", "Ku"]
    for i_band, band in enumerate(bands):
        print("[%2u] %s" %(i_band, band))

    resp = input("Enter number: ") or None

    try:
        custom_lnb_band = bands[int(resp)]
    except ValueError:
        raise ValueError("Please choose a number")

    if (sat['band'].lower() != custom_lnb_band.lower()):
        logging.error(
            "You must use a %s band LNB in order to receive from %s" %(
                sat['band'], sat['name']))
        exit(1)

    if (custom_lnb_band == "Ku"):
        custom_lnb_universal = _ask_yes_or_no("Is it a Universal Ku band LNB?")

        try:
            print(textwrap.fill(
                "An Universal Ku band LNB has two LO (local oscillator) " + \
                " frequencies. Typically the two frequencies are 9750 MHz " +
                "and 10600 MHz."))
            if (_ask_yes_or_no("Does your LNB have LO frequencies 9750 MHz and 10600 MHz?")):
                custom_lnb_lo_freq = [9750.0, 10600]
            else:
                resp = input("Inform the two LO frequencies in MHz, separated by comma: ")
                custom_lnb_lo_freq = resp.split(",")

        except ValueError:
            raise ValueError("Please enter a number")

    else:
        custom_lnb_universal = False

        try:
            custom_lnb_lo_freq = (input("LNB LO frequency in MHz: "))
        except ValueError:
            raise ValueError("Please enter a number")

    return {
        'vendor'    : "",
        'model'     : "",
        "lo_freq"   : custom_lnb_lo_freq,
        'universal' : custom_lnb_universal,
        'band'      : custom_lnb_band
    }


def _cfg_lnb(sat):
    """Configure LNB - either from preset or from custom specs

    Args:
        sat : user's satellite info

    """

    _print_header("LNB")

    print("Please, inform some specifications of your LNB.")

    print("\nAre you using one of the following LNBs?")
    for i_lnb, lnb in enumerate(lnbs):
        if (lnb['universal']):
            print("[%2u] %s %s (Universal Ku band LNBF)" %(i_lnb,
                                                           lnb['vendor'],
                                                           lnb['model']))
        else:
            print("[%2u] %s %s" %(i_lnb, lnb['vendor'], lnb['model']))


    if (_ask_yes_or_no("Are you using one of the LNBs above?")):
        resp = None
        while (not isinstance(resp, int)):
            try:
                resp = int(input("Which one? Enter LNB number: "))
            except ValueError:
                print("Please choose a number")
                continue

            if (resp >= len(lnbs)):
                print("Please choose number from 0 to %u" %(len(lnbs) - 1))
                resp = None
                continue

            lnb = lnbs[resp]
            print("%s %s" %(lnb['vendor'], lnb['model']))
            break
    else:
        lnb = _cfg_custom_lnb(sat)

    if (sat['band'].lower() != lnb['band'].lower()):
        logging.error("The LNB you chose cannot operate " + \
                      "in %s band (band of satellite %s)" %(sat['band'],
                                                            sat['alias']))
        exit(1)

    return lnb


def _cfg_frequencies(sat, setup, lnb):
    """Print summary of frequencies

    Inform the downlink RF frequency, the LNB LO frequency and the L-band
    frequency to be configured in the receiver.

    Args:
        sat   : user's satellite info
        setup : user's setup info
        lnb   : user's LNB info

    """
    _print_header("Frequencies")

    if (sat['band'].lower() == "ku"):
        if (lnb['universal']):
            assert(isinstance(lnb['lo_freq'], list)), \
                "An Universal LNB must have a list with two LO frequencies"
            assert(len(lnb['lo_freq']) == 2), \
                "An Universal LNB must have two LO frequencies"

            if (sat['dl_freq'] > ku_band_thresh):
                lo_freq = lnb['lo_freq'][1]
            else:
                lo_freq = lnb['lo_freq'][0]
        else:
            lo_freq = lnb['lo_freq']

        if_freq = sat['dl_freq'] - lo_freq

    elif (sat['band'].lower() == "c"):
        lo_freq = lnb['lo_freq']
        if_freq = lo_freq - sat['dl_freq']
    else:
        raise ValueError("Unknown satellite band")

    print("So, here are the frequencies of interest:\n")

    print("| Downlink %2s band frequency                     | %8.2f MHz |" %(sat['band'], sat['dl_freq']))
    print("| Your LNB local oscillator (LO) frequency       | %8.2f MHz |" %(lo_freq))
    print("| L-band frequency to configure on your receiver | %7.2f MHz  |" %(if_freq))
    print()

    if (lnb['universal']):
        print("NOTE regarding Universal LNB:\n")
        if (sat['dl_freq'] > ku_band_thresh):
            print(textwrap.fill(("The DL frequency of {} is in Ku high "
                                 "band (> {:.1f} MHz). Hence, you need to use "
                                 "the higher frequency LO ({:.1f} MHz) of your "
                                 "LNB. This requires a 22 kHz tone to be sent "
                                 "to the LNB."
            ).format(sat['alias'], ku_band_thresh, lo_freq)))
            print()
            if (setup['type'] == sdr_setup_type):
                print(textwrap.fill(("With a software-defined setup, you will "
                                     "need to place a 22 kHz tone generator "
                                     "inline between the LNB and the power "
                                     "inserter. Typically the tone generator "
                                     "uses power from the power inserter while "
                                     "delivering the tone directly to the "
                                     "LNB.")))
            else:
                print("The {} {} modem can generate the 22 kHz tone.".format(
                    setup['vendor'], setup['model']))
        else:
            print(textwrap.fill("The DL frequency of {} is in Ku low \
            band (< {:.1f} MHz). Hence, you need to use the lower (default) \
            frequency LO of your LNB.".format(sat['alias'], ku_band_thresh)))

    return {
        'dl'     : sat['dl_freq'],
        'lo'     : lo_freq,
        'l_band' : if_freq
    }


def _print_s400_instructions(info):
    """Print instruction for configuration of the Novra S400
    """
    _print_header("Novra S400")

    print("The Novra S400 is standalone modem, connected as follows:\n")

    print(("LNB ----> S400 (RF1 Interface) -- "
           "S400 (LAN 1 Interface) ----> Host / Network\n"))

    print(textwrap.fill("The S400 will receive from satellite and will output "
                        "multicast-addressed IP packets. The host will then "
                        "listen to these packets. Hence, the next step is to "
                        "configure both the S400 and the host."))

    _print_sub_header("S400 Configurations")
    print("Here is the list of configurations that are needed on the S400:")
    print()
    print("1. Go to Interfaces > RF1:\n")
    print("- DVB Mode: \"DVB-S2\"")
    print("- Carrier Freq.: {:.1f} MHz".format(info['freqs']['dl']))
    print("- LBand: {:.1f} MHz".format(info['freqs']['l_band']))
    print("- Symbol Rate: 1.0 MBaud")
    print("- MODCOD: AUTO")
    print("- Gold Code: 0")
    print("- Input Stream ID: 0")
    print("- LNB Power On: Enable")
    print("- L.O. Frequencies: {:.1f} MHz".format(info['freqs']['lo']))
    if (info['sat']['pol'] == "H"):
        print("- Polarization: Horiz./L")
    else:
        print("- Polarization: Vert./R")

    if (info['lnb']['universal'] and info['freqs']['dl'] > ku_band_thresh):
        print("- Band (Tone): \"High/On\"")
    else:
        print("- Band (Tone): \"Low/On\"")
    print("- Long Line Compensation: Disabled")
    print()
    print("2. Go to Interfaces > Data (LAN1):\n")
    print(textwrap.fill("Configure the IP address of the data interface. "
                        "This is the interface that will deliver IP "
                        "packets (data packets) received over satellite."))
    print()
    print("3. Go to Interfaces > M&C (LAN2):\n")
    print(textwrap.fill("Configure the IP address of the management and "
                        "control (M&C) interface. "
                        "This is the interface that will be used exclusively "
                        "for M&C traffic."))
    print()
    print("4. Go to Services > Tun1:\n")
    print("Scroll to \"Manage MPE PIDs\"")
    for pid in pids:
        print("- Enter %d on \"New PID\" and click \"Add\"." %(pid))

    _print_sub_header("Host Configurations")
    print("1. Run the following command on the host:")
    print("\n```\nsudo ./blocksat.py standalone -i ifname\n```\n")
    print(textwrap.fill("where \'ifname\' should be replaced with the name "
                        "of the network interface that is connected to the "
                        "S400. This interface can be connected directly to "
                        "S400 or via switch(es)."))


def _print_sdr_instructions(info):
    """Print instruction for configuration of an SDR setup
    """
    _print_header("SDR Setup")

    _print_sub_header("Connections")

    print("An SDR-based setup is assembled as follows:\n")

    print("LNB ----> Power Supply ----> RTL-SDR ----> Host\n")
    print(("The power supply is typically a \"Single Wire Multiswitch\" (SWM) "
          "supply. In this scenario, the LNB must be connected to the "
           "**powered** port, labeled \“Signal to SWM\”, and the "
           "**non-powered** port of the supply, labeled as \“Signal to IRD\", "
           "must be connected to the RTL-SDR."))

    _print_sub_header("Host Configuration")


def _gen_chan_conf(info):
    """Generate the channels.conf file"""

    _print_header("Linux USB Setup")

    print(textwrap.fill("This step will generate the channel configuration "
                        "file that is required when launching the USB "
                        "receiver in linux.") + "\n")

    cfg_file = "channels.conf"

    if (os.path.isfile(cfg_file)):
        print("Found previous %s file:" %(cfg_file))

        if (not _ask_yes_or_no("Remove and regenerate file?")):
            print("Configuration aborted.")
            return
        else:
            os.remove(cfg_file)

    with open(cfg_file, 'w') as f:
        f.write('[blocksat-ch]\n')
        f.write('\tDELIVERY_SYSTEM = DVBS2\n')
        f.write('\tFREQUENCY = %u\n' %(int(info['sat']['dl_freq']*1000)))
        if (info['sat']['pol'] == 'V'):
            f.write('\tPOLARIZATION = VERTICAL\n')
        else:
            f.write('\tPOLARIZATION = HORIZONTAL\n')
        f.write('\tSYMBOL_RATE = 1000000\n')
        f.write('\tINVERSION = AUTO\n')
        f.write('\tMODULATION = QPSK\n')
        f.write('\tVIDEO_PID = 32+33\n')

    print("File \"%s\" saved." %(cfg_file))


def configure(args):
    """Configure Blocksat Receiver setup

    """

    cfg_file = "config.json"

    user_info = _read_cfg_file()

    if (user_info is not None):
        print("Found previous configuration:")
        pprint(user_info, width=40, compact=False)
        if (not _ask_yes_or_no("Reset?")):
            print("Configuration aborted.")
            return

    user_sat   = _cfg_satellite()
    user_setup = _cfg_rx_setup()
    user_lnb   = _cfg_lnb(user_sat)
    user_freqs = _cfg_frequencies(user_sat, user_setup, user_lnb)

    user_info = {
        'sat'   : user_sat,
        'setup' : user_setup,
        'lnb'   : user_lnb,
        'freqs' : user_freqs
    }

    logging.debug(pformat(user_info))

    with open(cfg_file, 'w') as fd:
        json.dump(user_info, fd)

    print("Saved configurations on %s" %(cfg_file))

    if (user_setup['type'] == standalone_setup_type):
        _print_s400_instructions(user_info)
    elif (user_setup['type'] == sdr_setup_type):
        pass
    elif (user_setup['type'] == linux_usb_setup_type):
        _gen_chan_conf(user_info)

def find_adapter(prompt=True):
    """Find the DVB adapter

    Returns:
        Tuple with (adapter index, frontend index)

    """
    print("\n------------------------------ Find DVB Adapter " +
          "--------------------------------")
    ps     = subprocess.Popen("dmesg", stdout=subprocess.PIPE)
    try:
        output = subprocess.check_output(["grep", "frontend"], stdin=ps.stdout,
                                         stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError as grepexc:
        if (grepexc.returncode == 1):
            output = ""
            pass
    ps.wait()

    # Search a range of adapters. There is no command to list all adapters, so
    # we try to list each one individually using `dvbnet -a adapter_no -l`.
    adapters = list()
    for a in range(0,10):
        cmd     = ["dvbnet", "-a", str(a), "-l"]
        logging.debug("> " + " ".join(cmd))

        with open(os.devnull, 'w') as devnull:
            res = subprocess.call(cmd, stdout=devnull, stderr=devnull)
            if (res == 0):
                # Try a few frontends too
                for f in range(0,2):
                    try:
                        output = subprocess.check_output(["dvb-fe-tool", "-a",
                                                          str(a), "-f", str(f)])
                        line   = output.splitlines()[0].decode().split()
                        adapter = {
                            "adapter"  : str(a),
                            "frontend" : line[5].replace(")","").split("frontend")[-1],
                            "vendor"   : line[1],
                            "model"    : " ".join(line[2:4]),
                            "support"  : line[4]
                        }
                        adapters.append(adapter)
                        logging.debug(pformat(adapter))
                    except subprocess.CalledProcessError as e:
                        pass

    # If nothing was obtained using dvbnet, try to inspect dmesg logs
    if (len(adapters) == 0):
        lines       = output.splitlines()
        adapter_set = set() # use set to filter unique values
        adapters    = list()
        for line in lines:
            linesplit  = line.decode().split()
            i_adapter  = linesplit.index('adapter')
            i_frontend = linesplit.index('frontend')
            device     = linesplit[i_frontend + 2:]
            adapter = {
                "adapter"  : linesplit[i_adapter + 1],
                "frontend" : linesplit[i_frontend + 1],
                "vendor"   : device[0][1:],
                "model"    : " ".join(device[1:-1]),
                "support"  : device[-1][:-4].replace('(', '').replace(')', '')
            }
            adapter_set.add(json.dumps(adapter))

        # Process unique adapter logs
        for adapter in adapter_set:
            adapters.append(json.loads(adapter))
            logging.debug(pformat(json.loads(adapter)))

    dvb_s2_adapters = [a for a in adapters if ("DVB-S/S2" in a["support"])]
    logging.debug(dvb_s2_adapters)

    assert(len(dvb_s2_adapters) > 0), "No DVB-S2 adapters found"

    chosen_adapter = None
    for adapter in dvb_s2_adapters:
        print("Found DVB-S2 adapter: %s %s" %(adapter["vendor"],
                                              adapter["model"]))

        if (prompt):
            if (_ask_yes_or_no("Choose adapter?")):
                chosen_adapter = adapter
                logging.debug("Chosen adapter:")
                logging.debug(pformat(adapter))
                break

    if (not prompt):
        return

    if (chosen_adapter is None):
        raise ValueError("Please choose DVB-S2 adapter")

    return chosen_adapter["adapter"], chosen_adapter["frontend"]


def zap(adapter, frontend, conf_file, lnb="UNIVERSAL", output=None,
        timeout=None, monitor=False, scrolling=False):
    """Run zapper

    Args:
        adapter   : DVB adapter index
        frontend  : frontend
        conf_file : Path to channel configurations file
        lnb       : LNB type
        output    : Output filename (when recording)
        timeout   : Run the zap for this specified duration
        monitor   : Monitor mode. Monitors DVB traffic stats (throughput and
                    packets per second), but does not deliver data upstream.
        scrolling : Whether to print zap logs by scrolling rather than printing
                    always on the same line.

    Returns:
        Subprocess object

    """

    print("\n------------------------------ Tuning DVB Receiver " +
          "-----------------------------")
    print("Running dvbv5-zap")

    cmd = ["dvbv5-zap", "-c", conf_file, "-a", adapter, "-f", frontend, "-l", lnb, "-v"]

    if (output is not None):
        cmd = cmd + ["-o", output]

        if (os.path.exists(output)):
            print("File %s already exists" %(output))

            # The recording is such that MPEG TS packets are overwritten one by
            # one. For instance, if previous ts file had 1000 MPEG TS packets,
            # when overwriting, the tool would overwrite each packet
            # individually. So if it was stopped for instance after the first 10
            # MPEG TS packets, only the first 10 would be overwritten, the
            # remaining MPEG TS packets would remain in the ts file.
            #
            # The other option is to remove the ts file completely and start a
            # new one. This way, all previous ts packets are guaranteed to be
            # erased.
            raw_resp = input("Remove and start new (R) or Overwrite (O)? [R/O] ")
            response = raw_resp.lower()

            if (response == "r"):
                os.remove(output)
            elif (response != "o"):
                raise ValueError("Unknown response")

    if (timeout is not None):
        cmd = cmd + ["-t", timeout]

    if (monitor):
        assert(not scrolling), \
            "Monitor mode does not work with scrolling (line-by-line) logs"
        assert(output is None), \
            "Monitor mode does not work if recording (i.e. w/ -r flag)"
        cmd.append("-m")

    cmd.append("blocksat-ch")

    logging.debug("> " + " ".join(cmd))

    if (scrolling):
        ps = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, universal_newlines=True)
    else:
        ps = subprocess.Popen(cmd)

    return ps


def _dvbnet(adapter, ifname, pid, ule, existing_dvbnet_interfaces):
    """Start DVB network interface

    Args:
        adapter                    : DVB adapter index
        ifname                     : DVB network interface name
        pid                        : PID to listen to
        ule                        : Whether to use ULE framing
        existing_dvbnet_interfaces : List of dvbnet interfaces already
                                     configured for the adapter

    """

    assert(pid >= 32 and pid <= 8190), "PID not insider range 32 to 8190"

    if (ule):
        encapsulation = 'ULE'
    else:
        encapsulation = 'MPE'

    # Check if interface already exists
    try:
        res = subprocess.check_output(["ip", "addr", "show", "dev", ifname])
    except subprocess.CalledProcessError as e:
        res = None
        pass

    os_interface_exists = (res is not None)
    matching_dvbnet_if  = None

    # When the network interface exists in the OS, we also need to check if the
    # matching dvbnet device is configured according to what we want now
    if (os_interface_exists):
        print("Network interface %s already exists" %(ifname))

        for interface in existing_dvbnet_interfaces:
            if (interface['name'] == ifname):
                matching_dvbnet_if = interface
                break

    # Our indication that interface exists comes from "ip addr show
    # dev". However, it is possible that dvbnet does not have any interface
    # associated to an adapter, so check if we found anything:
    cfg_interface = False
    if (len(existing_dvbnet_interfaces) > 0 and matching_dvbnet_if is not None):
        # Compare to desired configurations
        if (matching_dvbnet_if['pid'] != pid or
            matching_dvbnet_if['encapsulation'] != encapsulation):
            cfg_interface = True

        if (matching_dvbnet_if['pid'] != pid):
            print("Current PID is %d. Set it to %d" %(
                matching_dvbnet_if['pid'], pid))

        if (matching_dvbnet_if['encapsulation'] != encapsulation):
            print("Current encapsulation is %s. Set it to %s" %(
                matching_dvbnet_if['encapsulation'], encapsulation
            ))
    else:
        cfg_interface = True

    # Create interface in case it doesn't exist or needs to be re-created
    if (cfg_interface):
        # If interface exists, but must be re-created, remove the existing one
        # first
        if (os_interface_exists):
            _rm_interface(adapter, ifname, verbose=False)

        adapter_dir = '/dev/dvb/adapter' + adapter
        if (not os.access(adapter_dir, os.W_OK)):
            raise PermissionError(
                "You need write permission on %s. " %(adapter_dir) +
                "Consider running as root." )

        if (ule):
            print("Launch %s using ULE encapsulation" %(ifname))
            ule_arg = "-U"
        else:
            print("Launch %s using MPE encapsulation" %(ifname))
            ule_arg = ""

        # Create interface for a given DVB adapter
        cmd     = ["dvbnet", "-a", adapter, "-p", str(pid), ule_arg]
        logging.debug("> " + " ".join(cmd))
        res     = subprocess.check_output(cmd)
        print(res.decode())
    else:
        print("Network interface %s already configured correctly" %(ifname))

def dvbnet(adapter, ifnames, pids, ule=False):
    """Start DVB network interfaces of a DVB adapter

    An adapter can have multiple dvbnet interfaces, one for each PID.

    Args:
        adapter  : DVB adapter index
        ifnames  : list of DVB network interface names
        pids     : List of PIDs to listen to on each interface
        ule      : Whether to use ULE framing

    """
    assert(isinstance(ifnames, list))
    assert(isinstance(pids, list))
    assert(len(ifnames) == len(pids)), \
        "Interface names and PID number must be vectors of the same length"

    # Find the dvbnet interfaces that already exist for the chosen adapter
    existing_dvbnet_iif = find_dvbnet_interfaces(adapter)

    print("\n------------------------------ Network Interface " +
          "-------------------------------")

    for ifname, pid in zip(ifnames, pids):
        _dvbnet(adapter, ifname, pid, ule, existing_dvbnet_iif)


def find_dvbnet_interfaces(adapter):
    """Find dvbnet interface(s) of a DVB adapter

    An adapter can have multiple dvbnet interfaces, one for each PID.

    Args:
        adapter: Corresponding DVB adapter

    Returns:
        interfaces : List of dvbnet interfaces

    """

    print("\n-------------------------- Find dvbnet interface(s) " +
          "----------------------------")
    cmd     = ["dvbnet", "-a", adapter, "-l"]
    logging.debug("> " + " ".join(cmd))
    res     = subprocess.check_output(cmd)

    interfaces = list()
    for line in res.splitlines():
        if ("Found device" in line.decode()):
            line_split    = line.decode().split()
            interface = {
                'dev'           : line_split[2][:-1],
                'name'          : line_split[4][:-1],
                'pid'           : int(line_split[8][:-1]),
                'encapsulation' : line_split[10]
            }
            logging.debug(pformat(interface))
            interfaces.append(interface)

    return interfaces


def _rm_interface(adapter, ifname, verbose=True):
    """Remove DVB net interface

    Args:
        adapter   : Corresponding DVB adapter
        interface : dvbnet interface number
        verbose   : Controls verbosity
    """

    if (verbose):
        print("\n------------------------------ Remove dvbnet interface " +
              "--------------------------------")
    cmd     = ["ip", "link", "set", ifname, "down"]
    logging.debug("> " + " ".join(cmd))
    res     = subprocess.check_output(cmd)

    if_number = ifname.split("_")[-1]
    cmd       = ["dvbnet", "-a", adapter, "-d", if_number]
    logging.debug("> " + " ".join(cmd))
    res       = subprocess.check_output(cmd)
    print(res.decode())


def _check_ip(net_if, ip_addr):
    """Check if interface has IP and if it matches target IP

    Args:
        net_if  : DVB network interface name
        ip_addr : Target IP address for the DVB interface slash subnet mask

    Returns:
        (Bool, Bool) Tuple of booleans. The first indicates whether interface
        already has an IP. The second indicates whether the interface IP (if
        existing) matches with respect to a target IP.

    """
    try:
        res = subprocess.check_output(["ip", "addr", "show", "dev", net_if])
    except subprocess.CalledProcessError as e:
        res = None
        pass

    has_ip = False
    ip_ok  = False
    for line in res.splitlines():
        if "inet" in line.decode() and "inet6" not in line.decode():
            has_ip    = True
            # Check if IP matches target
            inet_info = line.decode().split()
            inet_if   = IPv4Interface(inet_info[1])
            target_if = IPv4Interface(ip_addr)
            ip_ok     = (inet_if == target_if)
            break

    return has_ip, ip_ok


def _set_ip(net_if, ip_addr, verbose):
    """Set the IP of the DVB network interface

    Args:
        net_if    : DVB network interface name
        ip_addr   : Target IP address for the DVB interface slash subnet mask
        verbose   : Controls verbosity

    """
    has_ip, ip_ok = _check_ip(net_if, ip_addr)

    if (has_ip and not ip_ok):
        print("Interface %s has an IP, but it is not %s" %(net_if, ip_addr))
        print("Flush current IP address of %s" %(net_if))
        cmd = ["ip", "address", "flush", "dev", net_if]
        logging.debug("> " + " ".join(cmd))
        res = subprocess.check_output(cmd)

    if (not has_ip or not ip_ok):
        print("Assign IP address %s to %s" %(ip_addr, net_if))
        cmd = ["ip", "address", "add", ip_addr, "dev", net_if]
        logging.debug("> " + " ".join(cmd))
        res = subprocess.check_output(cmd)
    else:
        if (verbose):
            print("%s already has IP %s" %(net_if, ip_addr))


def set_ip(net_ifs, ip_addrs, verbose=True):
    """Set the IP of the DVB network interface

    Args:
        net_ifs   : List of DVB network interface names
        ip_addrs  : List of IP addresses for the DVB interface slash subnet mask
        verbose   : Controls verbosity

    """
    if (verbose):
        print("\n----------------------------- Interface IP Address " +
              "-----------------------------")

    for net_if, ip_addr in zip(net_ifs, ip_addrs):
        _set_ip(net_if, ip_addr, verbose)

def _check_rp_filters(dvb_if):
    """Check if reverse-path (RP) filters are configured on the interface

    Args:
        dvb_if : DVB network interface

    Return:
        True when configuration is already OK.

    """

    # Sysctl-ready interface name: replace a dot (for VLAN interface) with slash
    sysctl_dvb_if = dvb_if.replace(".", "/")

    # Check current configuration of DVB interface and "all" rule:
    dvb_cfg =  subprocess.check_output([
        "sysctl",
        "net.ipv4.conf." + sysctl_dvb_if + ".rp_filter"
    ]).split()[-1].decode()
    all_cfg =  subprocess.check_output([
        "sysctl",
        "net.ipv4.conf.all.rp_filter"
    ]).split()[-1].decode()

    return (dvb_cfg == "0" and all_cfg == "0")


def _set_rp_filters(dvb_if):
    """Disable reverse-path (RP) filtering for the DVB interface

    There are two layers of RP filters, one specific to the network interface
    and a higher level that controls the configurations for all network
    interfaces. This function disables RP filtering on the top layer (for all
    interfaces), but then enables RP filtering individually for each interface,
    except the DVB interface. This way, in the end only the DVB interface has RP
    filtering disabled.

    Args:
        dvb_if : DVB network interface

    """

    # Sysctl-ready interface name: replace a dot (for VLAN interface) with slash
    sysctl_dvb_if = dvb_if.replace(".", "/")

    # Check "all" rule:
    all_cfg =  subprocess.check_output([
        "sysctl",
        "net.ipv4.conf.all.rp_filter"
    ]).split()[-1].decode()


    # If "all" rule is already disabled, it is only necessary to disable the
    # target interface
    if (all_cfg == "0"):
        print("RP filter for \"all\" interfaces is already disabled")
        print("Disabling RP filter on interface %s" %(dvb_if))
        subprocess.check_output([
            "sysctl",
            "-w",
            "net.ipv4.conf." + sysctl_dvb_if + ".rp_filter=0"
        ])
    # If "all" rule is enabled, we will need to disable it. Also to preserve
    # RP filtering on all other interfaces, we will enable them manually.
    else:
        # Check interfaces
        ifs = os.listdir("/proc/sys/net/ipv4/conf/")

        # Enable all RP filters
        for interface in ifs:
            if (interface == "all" or interface == dvb_if):
                continue

            # Again, /proc/sys uses dot on VLANs normally, but sysctl does
            # not. Instead, it substitutes with slash. Replace here before using
            sysctl_interface = interface.replace(".", "/")

            # Check current configuration
            current_cfg =  subprocess.check_output([
                "sysctl",
                "net.ipv4.conf." + sysctl_interface + ".rp_filter"
            ]).split()[-1].decode()

            if (int(current_cfg) > 0):
                print("RP filter is already enabled on interface %s" %(
                    interface))
            else:
                print("Enabling RP filter on interface %s" %(interface))
                subprocess.check_output([
                    "sysctl",
                    "-w",
                    "net.ipv4.conf." + sysctl_interface + ".rp_filter=1"
                ])

        # Disable the overall RP filter
        print("Disabling RP filter on \"all\" rule")
        subprocess.check_output([
            "sysctl",
            "-w",
            "net.ipv4.conf.all.rp_filter=0"
        ])

        # And disable RP filtering on the DVB interface
        print("Disabling RP filter on interface %s" %(dvb_if))
        subprocess.check_output([
            "sysctl",
            "-w",
            "net.ipv4.conf." + sysctl_dvb_if + ".rp_filter=0"
        ])


def set_rp_filters(dvb_ifs):
    """Disable reverse-path (RP) filtering for the DVB interfaces

    Args:
        dvb_ifs : list of DVB network interfaces

    """
    assert(isinstance(dvb_ifs, list))

    print("\n----------------------------- Reverse Path Filters " +
          "-----------------------------")

    # Check if RP filters are already configured properly
    rp_filters_set = list()
    for dvb_if in dvb_ifs:
        rp_filters_set.append(_check_rp_filters(dvb_if))

    if (all(rp_filters_set)):
        print("Current RP filtering configurations are already OK")
        print("Skipping...")
        return

    print("Blocksat traffic is one-way and thus reverse path (RP) filtering " +
          "must be\ndisabled. The automatic solution disables RP filtering " +
          "on the DVB interface and\nenables RP filtering on all other " +
          "interfaces.")

    if (_ask_yes_or_no("OK to proceed?")):
        for dvb_if in dvb_ifs:
            _set_rp_filters(dvb_if)
    else:
        print("RP filtering configuration cancelled")


def _get_iptables_rules(net_if):
    """Get iptables rules that are specifically applied to a target interface

    Args:
        net_if : network interface name

    Returns:
        list of dictionaries with information of the individual matched rules

    """

    rules = list()

    # Get rules
    res = subprocess.check_output([
        "iptables", "-L", "-v", "--line-numbers"
    ])

    # Parse
    header1 = ""
    header2 = ""
    for line in res.splitlines():
        if ("Chain INPUT" in line.decode()):
            header1 = line.decode()

        if ("destination" in line.decode()):
            header2 = line.decode()

        if (net_if in line.decode()):
            rules.append({
                'rule' : line.decode().split(),
                'header1' : header1,
                'header2' : header2
            })

    return rules


def _is_iptables_igmp_rule_set(net_if, cmd):
    """Check if an iptables rule for IGMP is already configured

    Args:
        net_if : network interface name
        cmd    : list with iptables command

    Returns:
        True if rule is already set, False otherwise.

    """

    for rule in _get_iptables_rules(net_if):
        if (rule['rule'][3] == "ACCEPT" and rule['rule'][6] == cmd[6] and
            rule['rule'][4] == "igmp"):
            print("\nFirewall rule for IGMP already configured\n")
            print(rule['header1'])
            print(rule['header2'])
            print(" ".join(rule['rule']))
            print("\nSkipping...")
            return True

    return False

def _is_iptables_udp_rule_set(net_if, cmd):
    """Check if an iptables rule for UDP is already configured

    Args:
        net_if : network interface name
        cmd    : list with iptables command

    Returns:
        True if rule is already set, False otherwise.

    """

    for rule in _get_iptables_rules(net_if):
        if (rule['rule'][3] == "ACCEPT" and rule['rule'][6] == cmd[6] and
            (rule['rule'][4] == "udp" and rule['rule'][12] == cmd[10])):
            print("\nFirewall rule already configured\n")
            print(rule['header1'])
            print(rule['header2'])
            print(" ".join(rule['rule']))
            print("\nSkipping...")
            return True

    return False


def _add_iptables_rule(net_if, cmd):
    """Add iptables rule

    Args:
        net_if : network interface name
        cmd    : list with iptables command

    """

    # Set up iptables rules
    logging.debug("> " + " ".join(cmd))
    subprocess.check_output(cmd)

    # Check results
    res = subprocess.check_output([
        "iptables", "-L", "-v", "--line-numbers"
    ])

    for rule in _get_iptables_rules(net_if):
        print_rule = False

        if (rule['rule'][3] == "ACCEPT" and
            rule['rule'][6] == cmd[6] and
            rule['rule'][4] == cmd[4]):
            if (cmd[4] == "igmp"):
                print_rule = True
            elif (cmd[4] == "udp" and rule['rule'][12] == cmd[10]):
                print_rule = True

            if (print_rule):
                print("Added iptables rule:\n")
                print(rule['header1'])
                print(rule['header2'])
                print(" ".join(rule['rule']) + "\n")


def _configure_firewall(net_if, ports, igmp=False):
    """Configure firewallrules to accept blocksat traffic via DVB interface

    Args:
        net_if : DVB network interface name
        ports  : ports used for blocks traffic and API traffic
        igmp   : Whether or not to configure rule to accept IGMP queries

    """


    print("- Configure firewall rule to accept Blocksat traffic arriving " +
          "at interface %s\ntowards UDP ports %s." %(net_if, ",".join(ports)))

    cmd = [
        "iptables",
        "-I", "INPUT",
        "-p", "udp",
        "-i", net_if,
        "--match", "multiport",
        "--dports", ",".join(ports),
        "-j", "ACCEPT",
    ]

    if (not _is_iptables_udp_rule_set(net_if, cmd)):
        if (_ask_yes_or_no("Add corresponding ACCEPT firewall rule?")):
            _add_iptables_rule(net_if, cmd)
        else:
            print("\nFirewall configuration cancelled")


    # We're done, unless we also need to configure an IGMP rule
    if (not igmp):
        return

    # IGMP rule supports standalone DVB modems. The host in this case will need
    # to periodically send IGMP membership reports in order for upstream
    # switches between itself and the DVB modem to continue delivering the
    # multicast-addressed traffic. This overcomes the scenario where group
    # membership timeouts are implemented by the intermediate switches.
    print("Configure also a firewall rule to accept IGMP queries. This is " +
          "necessary when using a standalone DVB modem.")

    cmd = [
        "iptables",
        "-I", "INPUT",
        "-p", "igmp",
        "-i", net_if,
        "-j", "ACCEPT",
    ]

    if (not _is_iptables_igmp_rule_set(net_if, cmd)):
        if (_ask_yes_or_no("Add corresponding ACCEPT rule on firewall?")):
            _add_iptables_rule(net_if, cmd)
        else:
            print("\nIGMP firewall rule cancelled")


def configure_firewall(net_ifs, ports, igmp=False):
    """Configure firewallrules to accept blocksat traffic via DVB interface

    Args:
        net_ifs : List of DVB network interface names
        ports   : ports used for blocks traffic and API traffic
        igmp    : Whether or not to configure rule to accept IGMP queries

    """
    assert(isinstance(net_ifs, list))
    print("\n------------------------------- Firewall Rules " +
          "---------------------------------")

    for i, net_if in enumerate(net_ifs):
        _configure_firewall(net_if, ports, igmp)

        if (i < len(net_ifs) - 1):
            print("")


def launch(args):
    """Launch the DVB interface from scratch

    Handles the launch subcommand

    """

    assert(len(args.pid) == len(args.ip)), \
        "Number of PIDs (%u) defined by argument --pid " %(len(args.pid)) + \
        "does not match the number of IPs (%u) defined by " %(len(args.ip)) + \
        "argument --ip. Please define one IP address for each PID."

    # User info
    user_info = _read_cfg_file()

    while (user_info is None):
        print("Missing configuration")
        if (_ask_yes_or_no("Run now")):
            configure([])
        user_info = _read_cfg_file()

    # Find adapter
    if (args.adapter is None):
        adapter, frontend = find_adapter()
    else:
        adapter  = args.adapter
        frontend = args.frontend

    # Launch the DVB network interface - one interface for each PID of interest
    net_ifs  = list()
    for i_device in range(0, len(args.pid)):
        # Define interface name that is going to be generated by dvbnet
        net_if = "dvb" + adapter + "_" + str(i_device)
        net_ifs.append(net_if)

    # Create the interface(s)
    dvbnet(adapter, net_ifs, args.pid, ule=args.ule)

    # Set RP filters
    if (not args.skip_rp):
        set_rp_filters(net_ifs)

    # Set firewall rules
    if (not args.skip_firewall):
        configure_firewall(net_ifs, src_ports)

    # Set IP
    set_ip(net_ifs, args.ip)

    # Zap
    zap_ps = zap(adapter, frontend, args.chan_conf, lnb=args.lnb,
                 output=args.record_file, timeout=args.timeout,
                 monitor=args.monitor, scrolling=args.scrolling)

    # Handler for SIGINT
    def signal_handler(sig, frame):
        print('Stopping...')
        zap_ps.terminate()
        sys.exit(zap_ps.poll())

    signal.signal(signal.SIGINT, signal_handler)

    # Timer to periodically check the interface IP
    def reset_ip():
        set_ip(net_ifs, args.ip, verbose=False)
        timer        = threading.Timer(10, reset_ip)
        timer.daemon = True
        timer.start()

    reset_ip()

    # Listen to dvbv5-zap indefinitely
    if (args.scrolling):
        # Loop indefinitely over zap
        while (zap_ps.poll() is None):
            line = zap_ps.stderr.readline()
            if (line):
                print('\r%s: '%(time.strftime("%Y-%m-%d %H:%M:%S",
                                              time.gmtime())) +
                      line, end='')
            else:
                time.sleep(1)
    else:
        zap_ps.wait()
    sys.exit(zap_ps.poll())


def cfg_standalone(args):
    """Configurations for standalone DVB modem
    """
    set_rp_filters([args.interface])
    configure_firewall([args.interface], src_ports,
                       igmp=True)


def reverse_path_subcommand(args):
    """Call function that sets reverse path filters

    Handles the reverse-path subcommand

    """
    set_rp_filters([args.interface])


def firewall_subcommand(args):
    """Call function that sets firewall rules

    Handles the firewall subcommand

    """
    configure_firewall([args.interface], src_ports, igmp=args.standalone)


def find_adapter_subcommand(args):
    """Call function that finds the DVB adapter

    Handles the find-adapter subcommand

    """
    find_adapter(prompt=False)


def rm_subcommand(args):
    """Remove DVB interface

    """

    # Find adapter
    if (args.adapter is None):
        adapter, frontend = find_adapter()
    else:
        adapter = args.adapter

    interfaces     = find_dvbnet_interfaces(adapter)
    chosen_devices = list()

    if (len(interfaces) > 1):
        print("Choose net device to remove:")
        for i_dev, interface in enumerate(interfaces):
            print("[%2u] %s" %(i_dev, interface['name']))
        print("[ *] all")

        try:
            choice = input("Choose number: ")
            if (choice == "*"):
                i_chosen_devices = range(0, len(interfaces))
            else:
                i_chosen_devices = [int(choice)]
        except ValueError:
            raise ValueError("Please choose a number or \"*\" for all devices")

        for i_chosen_dev in i_chosen_devices:
            if (i_chosen_dev > len(interfaces)):
                raise ValueError("Invalid number")

            chosen_devices.append(interfaces[i_chosen_dev]['name'])

    elif (len(interfaces) == 0):
        print("No DVB network interfaces to remove")
        return
    else:
        # There is a single interface
        chosen_devices.append(interfaces[0]['name'])

    for chosen_dev in chosen_devices:
        if (not _ask_yes_or_no("Remove interface %s?" %(chosen_dev))):
            print("Aborting...")
            return

        _rm_interface(adapter, chosen_dev)


def main():
    """Main - parse command-line arguments and call subcommands

    """

    cwd        = os.path.dirname(os.path.realpath(__file__))
    parser     = argparse.ArgumentParser(prog="blocksat",
                                         description="Blocksat Receiver Helper")
    subparsers = parser.add_subparsers(title='subcommands',
                                       help='Target sub-command')

    # Config command
    cfg_parser = subparsers.add_parser('cfg',
                                       description="Configure Blocksat Rx setup",
                                       help='Define receiver and Bitcoin FIBRE \
                                       configurations')
    cfg_parser.set_defaults(func=configure)

    # Launch command
    launch_parser = subparsers.add_parser('launch',
                                          description="Set up the USB DVB-S2 interface",
                                          help='Launch USB DVB-S2 interface')

    launch_parser.add_argument('-c', '--chan-conf',
                               default=os.path.join(cwd, 'channels.conf'),
                               help='Channel configurations file ' +
                               '(default: channels.conf)')

    launch_parser.add_argument('-a', '--adapter',
                               default=None,
                               help='DVB-S2 adapter number (default: None)')

    launch_parser.add_argument('-l', '--lnb',
                               choices=lnb_options,
                               default="UNIVERSAL",
                               help='LNB type (default: "UNIVERSAL")')

    launch_parser.add_argument('-U', '--ule', default=False,
                               action='store_true',
                               help='Use ULE encapsulation instead of MPE ' +
                               '(default: False)')

    launch_parser.add_argument('--skip-rp', default=False, action='store_true',
                               help='Skip settting of reverse path filters ' + \
                               '(default: False)')

    launch_parser.add_argument('--skip-firewall', default=False,
                               action='store_true',
                               help='Skip configuration of firewall rules ' + \
                               '(default: False)')

    launch_parser.add_argument('-r', '--record-file', default=None,
                               help='Record MPEG-TS traffic into target file \
                               (default: None)')

    launch_parser.add_argument('-t', '--timeout', default=None,
                               help='Stop zapping after timeout - useful to \
                               control recording time (default: None)')

    launch_parser.add_argument('-m', '--monitor', default=False,
                               action='store_true',
                               help='Launch dvbv5-zap in monitor mode - useful \
                               to debug packet and bit rates (default: False)')

    launch_parser.add_argument('-s', '--scrolling', default=False,
                               action='store_true',
                               help='Print dvbv5-zap logs line-by-line, i.e. \
                               scrolling, rather than always on the same line \
                               (default: False)')

    launch_parser.add_argument('--pid', default=[32, 33],
                               type=int,
                               nargs='+',
                               help='List of PIDs to be listened to by dvbnet \
                               (default: 32,33)')

    launch_parser.add_argument('-i', '--ip',
                               default=['192.168.201.2/24', '192.168.201.3/24'],
                               nargs='+',
                               help='IP address set for each DVB-S2 net \
                               interface with subnet mask in CIDR notation \
                               (default: [192.168.201.2/24, 192.168.201.3/24])')

    launch_parser.set_defaults(func=launch)

    # Standalone command
    stdl_parser = subparsers.add_parser('standalone',
                                        description="Configure host to receive \
                                        data from standalone DVB-S2 modem",
                                        help='Configure host to receive from \
                                        standalone DVB-S2 modem')
    stdl_parser.add_argument('-i', '--interface', required = True,
                             help='Network interface (required)')
    stdl_parser.set_defaults(func=cfg_standalone)

    # Reverse path configuration command
    rp_parser = subparsers.add_parser('reverse-path', aliases=['rp'],
                                      description="Set reverse path filters",
                                      help='Set reverse path filters')

    rp_parser.add_argument('-i', '--interface', required = True,
                           help='Network interface (required)')

    rp_parser.set_defaults(func=reverse_path_subcommand)

    # Firewall configuration command
    fwall_parser = subparsers.add_parser('firewall',
                                         description="Set firewall rules",
                                         help='Set firewall rules')

    fwall_parser.add_argument('-i', '--interface', required = True,
                              help='Network interface (required)')

    fwall_parser.add_argument('--standalone', default=False,
                              action='store_true',
                              help='Configure for standalone DVB-S2 modem ' + \
                              '(default: False)')

    fwall_parser.set_defaults(func=firewall_subcommand)

    # Find adapter command
    find_parser = subparsers.add_parser('find',
                                        description="Find DVB-S2 adapter",
                                        help='Find DVB-S2 adapter')

    find_parser.set_defaults(func=find_adapter_subcommand)

    # Remove adapter command
    rm_parser = subparsers.add_parser('rm',
                                      description="Remove DVB-S2 adapter",
                                      help='Remove DVB-S2 adapter')

    rm_parser.add_argument('-a', '--adapter',
                           default=None,
                           help='DVB-S2 adapter number (default: None)')

    rm_parser.set_defaults(func=rm_subcommand)

    # Optional args
    parser.add_argument('--debug', action='store_true',
                        help='Debug mode (default: false)')

    args      = parser.parse_args()

    if (args.debug):
        logging.basicConfig(level=logging.DEBUG)
        logging.debug('[Debug Mode]')
    else:
        logging.basicConfig(level=logging.INFO)

    # Call corresponding subcommand
    # TODO what if func isn't defined here?
    if hasattr(args, 'func'):
        args.func(args)
    else:
        parser.print_help()


if __name__ == '__main__':
    main()