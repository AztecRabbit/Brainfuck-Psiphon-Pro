import os
import src
import argparse
import threading


def main():
    # utils
    utils = src.utils(__file__)

    # argparse
    parser = argparse.ArgumentParser(formatter_class=lambda prog: argparse.HelpFormatter(prog, max_help_position=52))
    parser.add_argument('-v', help='increase output verbosity', dest='verbose', action='store_true')
    parser.add_argument('-t', help='how many tunnels running', dest='tunnels', type=int)
    parser.add_argument('-r', help='region', dest='region', type=str)
    parser.add_argument('-f', help='frontend domains (e.g. cdn.net,cdn.net:443)', dest='frontend_domains', type=str)
    parser.add_argument('-w', help='whitelist request (e.g. akamai,akamai.net:443)', dest='whitelist_request', type=str)

    arguments = parser.parse_args()
    arguments.region = arguments.region.upper() if arguments.region else ''
    arguments.tunnels = arguments.tunnels if arguments.tunnels else 4
    arguments.frontend_domains = (
        utils.xfilter(arguments.frontend_domains.split(',')) if arguments.frontend_domains is not None else None)
    arguments.whitelist_request = (
        utils.xfilter(arguments.whitelist_request.split(',')) if arguments.whitelist_request is not None else None)

    if arguments.frontend_domains is None:
        arguments.frontend_domains = [
            'video.iflix.com',
            'videocdn-2.iflix.com',
        ]

        for i in [1, 2, 3, 6, 7, 8]:
            arguments.frontend_domains.append(f"iflix-videocdn-p{i}.akamaized.net")

    if arguments.whitelist_request is None:
        arguments.whitelist_request = ['akamai.net']

    arguments.frontend_domains.sort()
    arguments.whitelist_request.sort()

    # variables
    proxyrotator_host = str('0.0.0.0')
    proxyrotator_port = int('3080')
    inject_host = str('0.0.0.0')
    inject_port = int('8989')

    # config files
    if not os.path.exists(utils.real_path('/authorizations.txt')):
        with open(utils.real_path('/authorizations.txt'), 'w') as file:
            file.write('# write authorizations here\n\n\n')

    # log
    log = src.log()
    log.type = 1 if not arguments.verbose else 2
    log.prefix = 'INFO'
    log.value_prefix = (
        "datetime.datetime.now().strftime('[%H:%M:%S]{clear} [P1]::{clear} {color}{prefix}{clear} [P1]::{clear}')")

    try:
        # proxyrotator
        proxyrotator = src.proxyrotator((proxyrotator_host, proxyrotator_port), src.proxyrotator_handler)
        proxyrotator.liblog = log
        proxyrotator.proxies = []
        proxyrotator.username = 'aztecrabbit'
        proxyrotator.password = 'aztecrabbit'
        proxyrotator.buffer_size = 65535
        proxyrotator.socks_version = 5
        proxyrotator_thread = threading.Thread(target=proxyrotator.serve_forever)
        proxyrotator_thread.daemon = True
        proxyrotator_thread.start()
    except OSError:
        log.log_tab('Exception:', value_tab=[f"Port {proxyrotator_port} already in use", 'Exiting...'], color='[R1]')
        return

    # redsocks
    redsocks = src.redsocks()
    redsocks.liblog = log
    redsocks.ip = '127.0.0.1'
    redsocks.port = proxyrotator_port
    redsocks.type = 'socks5'
    redsocks.login = 'aztecrabbit'
    redsocks.password = 'aztecrabbit'
    redsocks.log_output = utils.real_path('/storage/redsocks/redsocks.log')
    redsocks.redsocks_config = utils.real_path('/storage/redsocks/redsocks.conf')
    redsocks.start()

    try:
        # psiphon
        psiphon = src.psiphon(inject_host, inject_port)
        psiphon.liblog = log
        psiphon.authorizations = utils.xfilter(open(utils.real_path('/authorizations.txt')).readlines())
        psiphon.region = arguments.region
        psiphon.tunnels = arguments.tunnels
        psiphon.tunnels_worker = 8 if arguments.tunnels <= 4 else arguments.tunnels + 4
        psiphon.proxyrotator = proxyrotator
        psiphon.load()

        if not len(psiphon.authorizations):
            log.log('Authorizations.txt not set!\n', color='[R1]')
            return

        for i, authorization in enumerate(psiphon.authorizations):
            psiphon_client_port = proxyrotator_port + 1 + i
            psiphon_client_thread = threading.Thread(
                target=psiphon.client, args=(psiphon_client_port, inject_port, authorization,))
            psiphon_client_thread.daemon = True
            psiphon_client_thread.start()

        log.log(f"Domain Fronting running on port {inject_port}", color='[G1]')
        log.log(f"Proxy Rotator running on port {proxyrotator_port}", color='[G1]')

        # inject
        inject = src.inject((inject_host, inject_port), src.inject_handler)
        inject.rules = [{
            'target-list': arguments.whitelist_request,
            'tunnel-type': '3',
            'remote-proxies': arguments.frontend_domains,
        }]
        inject.liblog = log
        inject.libredsocks = redsocks
        inject.socket_server_timeout = 1
        inject.serve_forever()
    except KeyboardInterrupt:
        inject.stop = True
        with log.lock:
            psiphon.stop()
            redsocks.stop()
            log.keyboard_interrupt()
            proxyrotator.stop()
    except PermissionError:
        log.log('Access denied: config file not exported automaticly, please run as root!\n', color='[R1]')
    except OSError as exception:
        log.log_tab('Exception:', value_tab=[exception, 'Exiting...'], color='[R1]')


if __name__ == '__main__':
    main()
