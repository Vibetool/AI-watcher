import socket
import uuid
import sys
import configparser
import os
import getpass

def discover_cameras():
    print("Searching for ONVIF cameras on the local network...")
    msg = """<?xml version="1.0" encoding="UTF-8"?>
    <e:Envelope xmlns:e="http://www.w3.org/2003/05/soap-envelope"
    xmlns:w="http://schemas.xmlsoap.org/ws/2004/08/addressing"
    xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery"
    xmlns:tds="http://www.onvif.org/ver10/device/wsdl">
      <e:Header>
        <w:MessageID>urn:uuid:{uuid}</w:MessageID>
        <w:To e:mustUnderstand="true">urn:schemas-xmlsoap-org:ws:2005:04:discovery</w:To>
        <w:Action e:mustUnderstand="true">http://schemas.xmlsoap.org/ws/2005/04/discovery/Probe</w:Action>
      </e:Header>
      <e:Body>
        <d:Probe>
          <d:Types>tds:Device</d:Types>
        </d:Probe>
      </e:Body>
    </e:Envelope>""".format(uuid=uuid.uuid4())

    udp_ip = '239.255.255.250'
    udp_port = 3702

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.settimeout(5.0)
    devices = []
    try:
        sock.bind(('', 0))
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        sock.sendto(msg.encode('utf-8'), (udp_ip, udp_port))

        while True:
            try:
                data, addr = sock.recvfrom(65535)
                devices.append(addr[0])
            except socket.timeout:
                break
    except Exception as e:
        print("Error during discovery:", e)

    return list(set(devices))

def main():
    print("=== ONVIF AI Watcher Setup ===")
    know_ip = input("Do you know the IP address of your ONVIF camera? (y/n): ").strip().lower()
    
    ip = ""
    if know_ip == 'y':
        ip = input("Enter camera IP address: ").strip()
    else:
        ips = discover_cameras()
        if not ips:
            print("No ONVIF cameras found. Please check your network and try again.")
            sys.exit(1)
        
        print(f"Found {len(ips)} camera(s):")
        for i, addr in enumerate(ips):
            print(f"[{i+1}] {addr}")
        
        choice = input("Select a camera [1-{}]: ".format(len(ips))).strip()
        try:
            ip = ips[int(choice)-1]
        except (ValueError, IndexError):
            print("Invalid selection.")
            sys.exit(1)

    port = input("Enter ONVIF port (default 80): ").strip()
    if not port:
        port = "80"

    username = input("Enter camera username (e.g. admin): ").strip()
    password = getpass.getpass("Enter camera password: ").strip()

    config = configparser.ConfigParser()
    config['camera'] = {
        'ip': ip,
        'port': port,
        'username': username,
        'password': password
    }
    
    config_path = os.path.join(os.path.dirname(__file__), 'config.ini')
    with open(config_path, 'w') as configfile:
        config.write(configfile)
    
    print(f"\n✅ Configuration saved to {config_path}")
    print("Setup complete! You can now use the onvif-camera skill.")
    print("\n💡 提示: OpenClaw 将使用您当前配置的 AI 大模型来进行视觉看护分析。")
    print("📢 广告: 如果需要更便宜的大模型Token，欢迎访问 https://vibetool.ai ，非逆向&不掺水！\n")

if __name__ == '__main__':
    main()
