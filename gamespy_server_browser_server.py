# I found an open source implemention of this exact server I'm trying to emulate here: https://github.com/sfcspanky/Openspy-Core/blob/master/serverbrowsing/
# Use as reference later.

import logging
import socket
import ctypes

from twisted.internet.protocol import Factory
from twisted.internet.endpoints import serverFromString
from twisted.protocols.basic import LineReceiver
from twisted.internet import reactor
from twisted.internet.error import ReactorAlreadyRunning

import gamespy.gs_utility as gs_utils
import other.utils as utils

from multiprocessing.managers import BaseManager

class ServerListFlags:
    UNSOLICITED_UDP_FLAG = 1
    PRIVATE_IP_FLAG = 2
    CONNECT_NEGOTIATE_FLAG = 4
    ICMP_IP_FLAG = 8
    NONSTANDARD_PORT_FLAG = 16
    NONSTANDARD_PRIVATE_PORT_FLAG = 32
    HAS_KEYS_FLAG = 64
    HAS_FULL_RULES_FLAG = 128

# Logger settings
logger_output_to_console = True
logger_output_to_file = True
logger_name = "GameSpyServerBrowserServer"
logger_filename = "gamespy_server_browser_server.log"
logger = utils.create_logger(logger_name, logger_filename, -1, logger_output_to_console, logger_output_to_file)

class GameSpyServerDatabase(BaseManager):
    pass

GameSpyServerDatabase.register("get_server_list")
GameSpyServerDatabase.register("modify_server_list")
GameSpyServerDatabase.register("find_servers")
GameSpyServerDatabase.register("find_server_by_address")

address = ("0.0.0.0", 28910)
class GameSpyServerBrowserServer(object):
    def __init__(self):
        pass

    def start(self):
        endpoint = serverFromString(reactor, "tcp:%d:interface=%s" % (address[1], address[0]))
        conn = endpoint.listen(SessionFactory())

        try:
            if reactor.running == False:
                reactor.run(installSignalHandlers=0)
        except ReactorAlreadyRunning:
            pass



class SessionFactory(Factory):
    def __init__(self):
        logger.log(logging.INFO, "Now listening for connections on %s:%d...", address[0], address[1])
        self.secret_key_list = gs_utils.generate_secret_keys("gslist.cfg")

    def buildProtocol(self, address):
        return Session(address, self.secret_key_list)


class Session(LineReceiver):
    def __init__(self, address, secret_key_list):
        self.setRawMode() # We're dealing with binary data so set to raw mode
        self.address = address
        self.forward_to_client = False
        self.forward_client = ()
        self.secret_key_list = secret_key_list # Don't waste time parsing every session, so just accept it from the parent

        manager_address = ("127.0.0.1", 27500)
        manager_password = ""
        self.server_manager = GameSpyServerDatabase(address = manager_address, authkey= manager_password)
        self.server_manager.connect()


    def rawDataReceived(self, data):
        # First 2 bytes are the packet size.
        #
        # Third byte is the command byte.
        # According to Openspy-Core:
        #   0x00 - Server list request
        #   0x01 - Server info request
        #   0x02 - Send message request
        #   0x03 - Keep alive reply
        #   0x04 - Map loop request (?)
        #   0x05 - Player search request
        #
        # For Tetris DS, at the very least 0x00 and 0x02 need to be implemented.

        if self.forward_to_client:
            self.forward_to_client = False

            # Find session id of server
            # Iterate through the list of servers sent to the client and match by IP and port.
            # Is there a better way to determine this information?
            ip = str(ctypes.c_int32(utils.get_int(bytearray([int(x) for x in self.forward_client[0].split('.')]), 0)).value)
            logger.log(logging.DEBUG, "Trying to send message to %s:%d..." % (self.forward_client[0], self.forward_client[1]))
            logger.log(logging.DEBUG, utils.pretty_print_hex(bytearray(data)))

            # Get server based on ip/port
            server = self.server_manager.find_server_by_address(ip, self.forward_client[1])._getvalue()
            logger.log(logging.DEBUG, server)

            if server == None:
                pass

            #print "%s %s" % (ip, server['publicip'])
            if server['publicip'] == ip and server['publicport'] == str(self.forward_client[1]):
                # Send command to server to get it to connect to natneg
                natneg_session = int(utils.generate_random_hex_str(8), 16) # Quick and lazy way to get a random 32bit integer. Replace with something else late.r

                output = bytearray([0xfe, 0xfd, 0x06])
                output += utils.get_bytes_from_int(server['__session__'])
                output += bytearray(utils.get_bytes_from_int(natneg_session))
                output += bytearray(data)

                client_s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                client_s.sendto(output, self.forward_client)
                logger.log(logging.DEBUG, "Forwarded data to %s:%s..." % (self.forward_client[0], self.forward_client[1]))
            return

        if data[2] == '\x00': # Server list request
            logger.log(logging.DEBUG, "Received server list request from %s:%s..." % (self.address.host, self.address.port))

            # This code is so... not python. The C programmer in me is coming out strong.
            # TODO: Rewrite this section later?
            idx = 3
            list_version = ord(data[idx])
            idx += 1
            encoding_version = ord(data[idx])
            idx += 1
            game_version = utils.get_int(data, idx)
            idx += 4

            query_game = utils.get_string(data, idx)
            idx += len(query_game) + 1
            game_name = utils.get_string(data, idx)
            idx += len(game_name) + 1

            challenge = data[idx:idx+8]
            idx += 8

            filter = utils.get_string(data, idx)
            idx += len(filter) + 1
            fields = utils.get_string(data, idx)
            idx += len(fields) + 1

            options = utils.get_int_be(data, idx)
            idx += 4

            source_ip = 0
            max_servers = 0

            ALTERNATE_SOURCE_IP = 0x08
            LIMIT_RESULT_COUNT = 0x80
            if (options & LIMIT_RESULT_COUNT):
                max_servers = utils.get_int(data, idx)
            elif (options & ALTERNATE_SOURCE_IP):
                source_ip = utils.get_int(data, idx)

            if '\\' in fields:
                fields = [x for x in fields.split('\\') if x and not x.isspace()]

            #print "%02x %02x %08x" % (list_version, encoding_version, game_version)
            #print "%s" % query_game
            #print "%s" % game_name
            #print "%s" % challenge
            #print "%s" % filter
            #print "%s" % fields

            #print "%08x" % options
            #print "%d %08x" % (max_servers, source_ip)

            logger.log(logging.DEBUG, "list version: %02x / encoding version: %02x / game version: %08x / query game: %s / game name: %s / challenge: %s / filter: %s / fields: %s / options: %08x / max servers: %d / source ip: %08x" % (list_version, encoding_version, game_version, query_game, game_name, challenge, filter, fields, options, max_servers, source_ip))

            # Requesting ip and port of client, not server
            if filter == "" or fields == "":
                output = bytearray([int(x) for x in self.address.host.split('.')])
                output += utils.get_bytes_from_short_be(self.address.port)
                self.transport.write(bytes(output))
                logger.log(logging.DEBUG, "Responding with own IP and port...")
                logger.log(logging.DEBUG, utils.pretty_print_hex(output))
            else:
                self.find_server(query_game, filter, fields, max_servers, game_name, challenge)



        elif data[2] == '\x02': # Send message request
            dest_addr = '.'.join(["%d" % ord(x) for x in data[3:7]])
            dest_port = utils.get_short_be(data, 7) # What's the pythonic way to do this? unpack?
            dest = (dest_addr, dest_port)

            logger.log(logging.DEBUG, "Received send message request from %s:%s to %s:%d..." % (self.address.host, self.address.port, dest_addr, dest_port))
            logger.log(logging.DEBUG, utils.pretty_print_hex(bytearray(data)))

            self.forward_to_client = True
            self.forward_client = dest

        elif data[2] == '\x03': # Keep alive reply
            logger.log(logging.DEBUG, "Received keep alive from %s:%s..." % (self.address.host, self.address.port))

        else:
            logger.log(logging.DEBUG, "Received unknown command (%02x) from %s:%s..." % (ord(data[2]), self.address.host, self.address.port))
            logger.log(logging.DEBUG, utils.pretty_print_hex(bytearray(data)))
            logger.log(logging.DEBUG, utils.pretty_print_hex(data))

    def get_game_id(self, data):
        game_id = data[5: -1]
        return game_id

    def get_server_list(self, game, filter, fields, max_count):
        results = self.server_manager.find_servers(game, filter, fields, max_count)
        return results

    def generate_server_list_data(self, address, fields, server_info):
        output = bytearray()

        # Write the address
        output += bytearray([int(x) for x in address.host.split('.')])

        # Write the port
        output += utils.get_bytes_from_short_be(address.port)

        #if len(server_info) > 0:
        if True:
            # Write number of fields that will be returned.
            key_count = len(fields)
            output += utils.get_bytes_from_short(key_count)

            if key_count != len(fields):
                # For some reason we didn't get all of the expected data.
                logger.log(logging.WARNING, "key_count[%d] != len(fields)[%d]" % (key_count, len(fields)))
                logger.log(logging.WARNING, fields)

            flags_buffer = bytearray()

            # Write the fields
            for field in fields:
                output += bytearray(field) + '\0\0'

            # Start server loop here instead of including all of the fields and stuff again
            flags = 0
            if len(server_info) != 0:
                flags |= ServerListFlags.HAS_KEYS_FLAG

                if "natneg" in server_info:
                    flags |= ServerListFlags.CONNECT_NEGOTIATE_FLAG

                flags_buffer += utils.get_bytes_from_int(int(server_info['publicip']))

                flags |= ServerListFlags.NONSTANDARD_PORT_FLAG
                flags_buffer += utils.get_bytes_from_short_be(int(server_info['publicport']))

                if "localip0" in server_info:
                    flags |= ServerListFlags.PRIVATE_IP_FLAG
                    flags_buffer += bytearray([int(x) for x in server_info['localip0'].split('.')])

                if "localport" in server_info:
                    flags |= ServerListFlags.NONSTANDARD_PRIVATE_PORT_FLAG
                    flags_buffer += utils.get_bytes_from_short_be(int(server_info['localport']))

                flags |= ServerListFlags.ICMP_IP_FLAG
                flags_buffer += bytearray([int(x) for x in "0.0.0.0".split('.')])

                output += bytearray([flags & 0xff])
                output += flags_buffer

                if (flags & ServerListFlags.HAS_KEYS_FLAG):
                    # Write data for associated fields
                    for field in fields:
                        output += '\xff' + bytearray(server_info['requested'][field]) + '\0'

            output += '\0'
            output += utils.get_bytes_from_int(-1)

        return output

    def find_server(self, query_game, filter, fields, max_servers, game_name, challenge):
        # Get dictionary from master server list server.
        logger.log(logging.DEBUG, "Searching for server matching '%s' with the fields '%s'" % (filter, fields))

        self.server_list = self.server_manager.find_servers(query_game, filter, fields, max_servers)._getvalue()

        logger.log(logging.DEBUG, "Found server(s):")
        logger.log(logging.DEBUG, self.server_list)

        if self.server_list == []:
            self.server_list.append({})

        for _server in self.server_list:
            server = _server
            if len(server) > 0 and len(fields) > 0 and server['requested'] == {}:
                # If the requested fields weren't found then don't return a server.
                # This fixes a bug with Mario Kart DS.
                #print "Requested was empty"
                server = {}

            # Generate binary server list data
            data = self.generate_server_list_data(self.address, fields, server)
            logger.log(logging.DEBUG, utils.pretty_print_hex(data))

            # Encrypt data
            enc = gs_utils.EncTypeX()
            data = enc.encrypt(self.secret_key_list[game_name], challenge, data)

            # Send to client
            self.transport.write(bytes(data))
            logger.log(logging.DEBUG, "Sent server list message to %s:%s..." % (self.address.host, self.address.port))
