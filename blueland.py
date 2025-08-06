#!/usr/bin/env python3

'''
blueland - A reactive Bluetooth frontend daemon for Hyprland users.
This library is free software; you can redistribute it and/or modify it under the terms of the GNU Lesser General Public License as published by the Free Software Foundation; either version 2.1 of the License, or (at your option) any later version.
This library is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU Lesser General Public License for more details.
You should have received a copy of the GNU Lesser General Public License along with this library; if not, see <https://www.gnu.org/licenses/>.
'''

from dbus_next.service import ServiceInterface, method
from dbus_next.aio import MessageBus
from dbus_next import Variant, BusType
import os
import json
import asyncio
import subprocess

AGENT_PATH = '/org/bluez/Blueland/Agent'
OBEX_AGENT_PATH = '/org/bluez/Blueland/ObexAgent'
SOCKET_PATH = f'/run/user/{os.getuid()}/blueland/blueland.sock'

UUID_NAMES = {
    "0000111e-0000-1000-8000-00805f9b34fb": "Hands-Free Profile (Calls)",
    "0000110d-0000-1000-8000-00805f9b34fb": "A2DP Sink (Media Audio)",
    "0000110e-0000-1000-8000-00805f9b34fb": "AVRCP Controller (Media Controls)",
}

clients = set()  # Track connected clients

def zenity_prompt(prompt_text):
    try:
        result = subprocess.run(
            ['zenity', '--question', '--text', prompt_text],
            capture_output=True
        )
        return 'yes' if result.returncode == 0 else 'no'
    except Exception as e:
        print("Zenity failed:", e)
        return 'no'
    
async def handle_client(reader, writer):
    print("Client connected")
    clients.add(writer) 

    try:
        await writer.wait_closed()
    finally:
        clients.remove(writer)
        print("Client disconnected")

class BluetoothAgent(ServiceInterface):
    # Well function handling, what else
    def __init__(self):
        super().__init__('org.bluez.Agent1')

    @method()
    def RequestConfirmation(self, device: 'o', passkey: 'u'): # type: ignore
        response = zenity_prompt(f"Confirm pairing with passkey: {passkey}")
        if response.lower() != 'yes':
            raise Exception("User rejected pairing")
        return None

    @method()
    def Cancel(self):
        print("Pairing canceled.")

    @method()
    def RequestPinCode(self, device: 'o') -> 's': # type: ignore
        pin = zenity_prompt("Enter PIN", options='')
        return pin

    @method()
    def RequestPasskey(self, device: 'o') -> 'u': # type: ignore
        passkey = zenity_prompt("Enter Passkey", options='')
        return int(passkey)
    
    @method()
    def AuthorizeService(self, device: 'o', uuid: 's'): # type: ignore
        name = UUID_NAMES.get(uuid.lower(), f"Unknown Service ({uuid})")
        response = zenity_prompt(f"Allow device to use:\n{name}")
        if response.lower() != 'yes':
            raise Exception("Service authorization denied")
        return None
    
class BluelandFrontend(ServiceInterface):
    # Frontend for the agent, to be used by other applications
    def __init__(self, adapter, bus, fbus):
        super().__init__('org.blueland.Frontend')
        self.adapter = adapter
        self.bus = bus
        self.fbus = fbus
        self.known_devices = {}

    async def setup(self):
        obj_manager = self.bus.get_proxy_object('org.freedesktop.DBus', '/org/freedesktop/DBus', await self.bus.introspect('org.freedesktop.DBus', '/org/freedesktop/DBus'))
        dbus_iface = obj_manager.get_interface('org.freedesktop.DBus')
        await dbus_iface.call_add_match("type='signal',interface='org.freedesktop.DBus.ObjectManager',member='InterfacesAdded'")
        self.bus.add_message_handler(self._handle_interfaces_added)

    def _handle_interfaces_added(self, message):
        if message.interface != 'org.freedesktop.DBus.ObjectManager':
            return

        path = message.body[0]
        interfaces = message.body[1]
        if 'org.bluez.Device1' in interfaces:
            device_info = interfaces['org.bluez.Device1']
            mac = device_info.get('Address', Variant('s', 'Unknown')).value
            name = device_info.get('Name', Variant('s', 'Unknown')).value
            self.known_devices[mac] = {
                'name': name,
                'mac': mac,
                'path': path,
            }
            print(f"Device found: {name} ({mac}) at {path}")
            for client in clients:
                try:
                    client.write((json.dumps({"name": name,"mac": mac,"path": path}) + "\n").encode())
                except Exception as e:
                    print(f"Failed to send to client: {e}")

    @method()
    async def DiscoverDevices(self) -> 'as': # type: ignore
        devices = {}

        # Step 1: Pull all known (paired) devices first
        introspect = await self.bus.introspect('org.bluez', '/')
        manager_obj = self.bus.get_proxy_object('org.bluez', '/', introspect)
        objmanager = manager_obj.get_interface('org.freedesktop.DBus.ObjectManager')
        objects = await objmanager.call_get_managed_objects()
        for path, interfaces in objects.items():
            if 'org.bluez.Device1' in interfaces:
                props = interfaces['org.bluez.Device1']
                mac = props.get('Address', Variant('s', 'unknown')).value
                name = props.get('Name', Variant('s', mac)).value
                self.known_devices[mac] = {
                    'name': name,
                    'mac': mac,
                    'path': path,
                }

                # Push to frontend via socket
                for client in clients:
                    try:
                        client.write((json.dumps({
                            "name": name,
                            "mac": mac,
                            "path": path
                        }) + '\n').encode())
                    except Exception as e:
                        print(f"Failed to send to client: {e}")

        # Step 2: Begin live discovery
        await self.adapter.call_start_discovery()
        print("Discovery started...")
        await asyncio.sleep(10)
        await self.adapter.call_stop_discovery()
        print("Discovery stopped.")

        # Step 3: Merge live discovered devices
        for mac, info in self.known_devices.items():
            name = info["name"]
            devices[mac] = name  # overwrites if duplicate MAC

        # Format list for D-Bus return
        result = [f"{name} ({mac})" for mac, name in devices.items()]
        result.append(f"Live devices feed is available via unix socket at {SOCKET_PATH}")
        return result

    @method()
    async def DeviceState(self, mac: 's') -> 'a{sv}': # type: ignore
        info = self.known_devices.get(mac)
        if not info:
            return {}

        path = info["path"]
        device_obj = self.bus.get_proxy_object('org.bluez', path, await self.bus.introspect('org.bluez', path))
        props_iface = device_obj.get_interface('org.freedesktop.DBus.Properties')
        
        keys = ['Name', 'Address', 'Paired', 'Connected', 'Trusted', 'RSSI', 'UUIDs']
        state = {}

        for key in keys:
            try:
                val = await props_iface.call_get('org.bluez.Device1', key)
                state[key] = val
            except Exception:
                pass  # Silent skip if unsupported

        return state

    @method()
    async def PairConnDevice(self, mac: 's') -> 's': # type: ignore
        if not self.known_devices:
            raise Exception("No devices cached. Please run DiscoverDevices first.")

        info = self.known_devices.get(mac)  
        if not info:
            raise Exception(f"Device with MAC {mac} not found")

        device_path = info["path"]

        # Prepare interfaces
        device_introspection = await self.bus.introspect('org.bluez', device_path)
        available = [iface.name for iface in device_introspection.interfaces]
        print(f"Available interfaces on {device_path}: {available}")
        device_obj = self.bus.get_proxy_object('org.bluez', device_path, device_introspection)
        if 'org.bluez.Device1' not in available:
            print(f"{device_path} has no Device1 interface — skipping.")
            return f"{info['name']} is not available right now."
        device = device_obj.get_interface('org.bluez.Device1')
        props_iface = device_obj.get_interface('org.freedesktop.DBus.Properties')

        # Check if paired
        is_paired = (await props_iface.call_get('org.bluez.Device1', 'Paired'))
        try:
            if not is_paired:
                await device.call_pair()
                await props_iface.call_set('org.bluez.Device1', 'Trusted', Variant('b', True))
                print(f"Paired and trusted {info['name']}")
            else:
                print(f"{info['name']} already paired — skipping")

            await device.call_connect()
            return f"Connected to {info['name']}"
        except Exception as e:
            raise Exception(f"Failed to connect to {info['name']}: {e}")

    @method()
    async def DisconnectDevice(self, mac: 's') -> 's': # type: ignore
        if not self.known_devices:
            raise Exception("No devices cached. Please run DiscoverDevices first.")

        info = self.known_devices.get(mac)
        if not info:
            return f"Device {mac} not found"

        device_path = info["path"]
        device_obj = self.bus.get_proxy_object('org.bluez', device_path, await self.bus.introspect('org.bluez', device_path))
        device = device_obj.get_interface('org.bluez.Device1')

        try:
            await device.call_disconnect()
            return f"Device {info['name']} disconnected."
        except Exception as e:
            return f"Failed to disconnect {info['name']}: {e}"

    @method()
    async def RemoveDevice(self, mac: 's') -> 's': # type: ignore
        if not self.known_devices:
            raise Exception("No devices cached. Please run DiscoverDevices first.")

        info = self.known_devices.get(mac)
        if not info:
            return f"Device {mac} not found"

        device_path = info["path"]
        adapter_path = '/org/bluez/hci0'
        adapter_obj = self.bus.get_proxy_object('org.bluez', adapter_path, await self.bus.introspect('org.bluez', adapter_path))
        adapter = adapter_obj.get_interface('org.bluez.Adapter1')

        try:
            await adapter.call_remove_device(device_path)
            return f"Device {info['name']} removed from known devices."
        except Exception as e:
            return f"Failed to remove {info['name']}: {e}"
        
    @method()
    async def SendFiles(self, mac: 's', filepath: 's') -> 's': # type: ignore
        if not self.known_devices:
            raise Exception("No devices cached. Please run DiscoverDevices first.")

        info = self.known_devices.get(mac)
        if not info:
            return f"Device {mac} not found"

        # Step 1: Create OBEX session
        obex_path = '/org/bluez/obex'
        obex_obj = self.fbus.get_proxy_object('org.bluez.obex', obex_path, await self.fbus.introspect('org.bluez.obex', obex_path))
        client = obex_obj.get_interface('org.bluez.obex.Client1')

        try:
            session_path = await client.call_create_session(mac, {'Target': Variant('s', 'opp')})
        except Exception as e:
            return f"Failed to create OBEX session with {mac}: {e}"

        # Step 2: Get ObjectPush1 interface
        session_obj = self.fbus.get_proxy_object('org.bluez.obex', session_path, await self.fbus.introspect('org.bluez.obex', session_path))
        push_iface = session_obj.get_interface('org.bluez.obex.ObjectPush1')

        # Step 3: Send file
        try:
            await push_iface.call_send_file(filepath)
            return f"File {os.path.basename(filepath)} sent to {info['name']} ({mac})."
        except Exception as e:
            return f"Failed to send file to {info['name']}: {e}"


class BluelandObexAgent(ServiceInterface):
    def __init__(self, bus):
        super().__init__('org.bluez.obex.Agent1')
        self.bus = bus
        self.download_dir = os.path.expanduser("~/")
        self.auto_accept = False

    @method()
    async def AuthorizePush(self, transfer: 'o') -> 's': # type: ignore
        # Connect to the transfer object and inspect its properties
        transfer_obj = self.bus.get_proxy_object('org.bluez.obex', transfer, await self.bus.introspect('org.bluez.obex', transfer))
        props = transfer_obj.get_interface('org.freedesktop.DBus.Properties')
        name = await props.call_get('org.bluez.obex.Transfer1', 'Name')
        size = await props.call_get('org.bluez.obex.Transfer1', 'Size')

        print(f"Incoming file: {name.value} ({size.value} bytes) from {transfer}")

        if self.auto_accept:
            return os.path.join(self.download_dir, name.value)
        else:
            response = zenity_prompt(f"Accept file {name.value} ({size.value} bytes)?")
            if response.lower() == 'yes':
                return os.path.join(self.download_dir, name.value)
            else:
                raise Exception("Rejected by policy")

    @method()
    def Cancel(self, device: 'o'): # type: ignore
        print(f"Transfer from {device} cancelled.")


async def main():
    # It might get confusing but I'll explain it, I guess
    bus = await MessageBus(bus_type=BusType.SYSTEM).connect()

    # We're asking BlueZ what it wants us to do
    bluez_introspection = await bus.introspect('org.bluez', '/org/bluez')
    # We get the AgentManager interface and claim it
    manager = bus.get_proxy_object('org.bluez', '/org/bluez', bluez_introspection).get_interface('org.bluez.AgentManager1')
    await manager.call_register_agent(AGENT_PATH, 'DisplayYesNo')
    await manager.call_request_default_agent(AGENT_PATH)
    print("Agent registered and listening.")

    # We're claiming the adapter now, so we can interact with it
    # This is the main Bluetooth adapter, usually hci0
    adapter_introspection = await bus.introspect('org.bluez', '/org/bluez/hci0')
    adapter_obj = bus.get_proxy_object('org.bluez', '/org/bluez/hci0', adapter_introspection)
    adapter = adapter_obj.get_interface('org.bluez.Adapter1')

    # Now we insert it all together
    agent = BluetoothAgent() # Defining in the bus where our functions are
    bus.export(AGENT_PATH, agent) # Just inserting the class, objects, blablabla to the bus

    # Also, frontend for you nerds
    fbus = await MessageBus(bus_type=BusType.SESSION).connect()
    frontend = BluelandFrontend(adapter, bus, fbus)
    await fbus.request_name('org.blueland.Frontend')
    fbus.export('/org/blueland/Frontend', frontend)
    frontend.agent = agent  # Link the frontend to the agent
    await frontend.setup()  # Setup the frontend to listen for device events

    # Obex agent for file transfers
    obex_agent = BluelandObexAgent(fbus)
    fbus.export(OBEX_AGENT_PATH, obex_agent)

    # Tell BlueZ's obex manager that this is the default agent
    try:
        obex_introspection = await fbus.introspect('org.bluez.obex', '/org/bluez/obex')
    except TimeoutError:
        print("Reattempting obex introspection...")
        while True:
            try:
                obex_introspection = await fbus.introspect('org.bluez.obex', '/org/bluez/obex')
                break  # Break the loop if introspection is successful
            except TimeoutError:
                print("Reattempting obex introspection...")
    obex_manager = fbus.get_proxy_object('org.bluez.obex', '/org/bluez/obex', obex_introspection).get_interface('org.bluez.obex.AgentManager1')
    await obex_manager.call_register_agent(OBEX_AGENT_PATH)

    # Unix socket setup
    # Remove existing socket if it exists
    if os.path.exists(SOCKET_PATH):
        os.remove(SOCKET_PATH)

    # Create parent directory if needed
    os.makedirs(os.path.dirname(SOCKET_PATH), exist_ok=True)

    # Start the server
    server = await asyncio.start_unix_server(handle_client, path=SOCKET_PATH)
    print(f"Unix socket started at {SOCKET_PATH}")
    
    # Run the server and keep the app running
    await asyncio.gather(
        server.serve_forever(),  # Handle incoming socket clients
        asyncio.get_running_loop().create_future()  # Keep the app from exiting
    )

if os.name == 'nt':
    print("This script is for Linux systems only.")
    exit(0)
else:
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nAgent stopped by user. Bye!")