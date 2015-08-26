import socket
import logging
import multiprocessing
import select
import os
from datetime import datetime
import urllib.parse


HTTP_VERSION = "HTTP/1.1"

STATUS_CODES = {
    "OK": "200 OK",
    "Bad Request": "400 Bad Request",
    "Not Found": "404 Not Found",
    "Not Implemented": "501 Not Implemented"
}

# From http://www.w3.org/Protocols/rfc2616/rfc2616-sec5.html
METHODS = ["OPTIONS", "GET", "HEAD", "POST", "PUT", "DELETE", "TRACE", "CONNECT"]

# The methods GET and HEAD MUST be supported by all general-purpose servers. All other methods are OPTIONAL
# These methods are the methods that are currently implemented. Any other request will give a 501 error
IMPLEMENTED_METHODS = ["GET", "HEAD"]


class HTTPBadRequest(Exception):
    pass


class HTTP_Message:
    """
    The HTTP request message is in the format:
        Request line (for requests) or Status line (for responses)
        Headers, each on its own line
        An empty line
        HTTP message body data (optional, if not supplied, empty line)

    Lines are separated by CRLF (carriage return \r followed by line feed \n characters)
    """
    def __init__(self, data=None):
        self.type = None  # Request or Response
        self.request_line = {}
        self.status_line = {}
        self.headers = {}
        self.body = ""

        if data is not None:
            self.parse_request(data)

    def parse_request(self, bytestring):
        """
        Parses the given request bytestring
        """
        self.type = "Request"

        # Many times a request will be 0 bytes. The smallest request would be "GET / HTTP/x.x/r/n" which is 16 bytes
        if len(bytestring) < 16:
            raise HTTPBadRequest

        req = bytestring.decode("utf-8")
        lines = req.split("\r\n")

        request_line = lines[0]
        headers = lines[1:-2]
        http_message_line = lines[-1]

        # Parse request line
        request_line_parts = request_line.split(" ")
        self.request_line["Method"] = request_line_parts[0]
        self.request_line["Request-URI"] = request_line_parts[1]
        self.request_line["HTTP-Version"] = request_line_parts[2]

        # Parse headers
        for line in headers:
            (field, value) = line.split(": ")
            self.headers[field] = value

        # Lastly, the HTTP message
        self.body = http_message_line  # Should be blank for requests

    def create_response(self, status, message):
        """
        Creates a response HTTP message given a status code name (e.g. "OK") and an HTTP message body
        """
        self.type = "Response"
        self.status_line = HTTP_VERSION + " " + STATUS_CODES[status]

        # Set optional headers
        self.headers["Connection"] = "close"
        self.headers["Server"] = "PythonServer/1.0 (Windows 10)"
        self.headers["Date"] = datetime.now().strftime("%a, %d %b %Y %H:%M:%S ") + "EST"  # TODO: get timezone from OS

        if message is not None:
            self.body = message

        return self.get_bytestring()

    def get_bytestring(self):
        """
        Converts this HTTP message into a bytestring suitable to be sent over a socket
        """
        newline = b"\r\n"
        ret = b""

        # Status line
        ret += bytes(self.status_line, "utf-8") + newline

        # Headers
        for field, value in self.headers.items():
            ret += bytes(field, "utf-8") + b": " + bytes(value, "utf8") + newline

        # Empty line
        ret += newline

        # message body
        if self.body:
            ret += bytes(self.body, "utf8")
        ret += newline

        return ret


class HTTP_Server:
    def __init__(self, host="localhost", port=80, backlog=10):
        """
        Initialize the HTTP server
        :param host: the hostname
        :param port: the port to be listened on
        :param backlog: the number of connections that will be queued before connections will be refused
        """
        #logging.info("Starting server on host " + host + " and port " + str(port))
        #logging.debug("Socket backlog is set to " + str(backlog))
        
        self.socket = socket.socket()
        self.socket.bind((host, port))
        self.socket.listen(backlog)

    def set_web_root(self, path):
        #logging.debug("Setting the web root to " + path)
        self.web_root = os.path.normpath(path)

    def parse_request(self, req):
        """
        Returns an appropriate HTTP_Message response given an HTTP_Message request.

        Can process any HTTP method in IMPLEMENTED_METHODS, any other method returns a Not Implemented response message.
        """
        method = req.request_line["Method"]

        if method not in METHODS:
            #logging.warning("Client requested unknown HTTP method " + method)
            return self.serve_error("Bad Request")

        if method not in IMPLEMENTED_METHODS:
            #logging.warning("Client requested unimplemented HTTP method " + method)
            return self.serve_error("Not Implemented")

        if method == "GET":
            #logging.debug("Client requested GET")
            return self.http_method_get(req)
        elif method == "HEAD":
            #logging.debug("Client requested HEAD")
            return self.http_method_head(req)

    def http_method_get(self, req, send_body=True):
        """
        Returns an appropriate HTTP_Message given an HTTP_Message GET request.

        If a file is requested in the request's URI string, a response
        """
        uri = urllib.parse.unquote(req.request_line["Request-URI"])  # parse %xx special url characters
        path = os.path.join(self.web_root, uri[1:])  # ignore first slash of uri

        response = HTTP_Message()
        message_body = None

        if os.path.isdir(path):
            #logging.debug("The request's URI is a directory. Attempting to find index file")
            # if either index.html or index.htm exists:
            for index_file in [os.path.join(path, "index.html"), os.path.join(path, "index.htm")]:
                if os.path.isfile(index_file):
                    message_body = self.get_file(index_file)
                    break

            # If no index file then show directory listing of this directory
            if message_body is None:
                message_body = self.get_directory_listing(path, uri)

        # If path is not a directory, maybe it's a file
        elif os.path.isfile(path):
            #logging.debug("The request's URI is a file")
            message_body = self.get_file(path)
        else:
            #logging.warning("File not found " + uri)
            return self.serve_error("Not Found", send_body)

        # We have a message body, time to respond
        if send_body:
            return response.create_response("OK", message_body)
        else:
            return response.create_response("OK", None)

    def http_method_head(self, req):
        """
        Returns an appropriate HTTP_Message given an HTTP_Message HEAD request.

        A HEAD request is the same as a GET request except it will not include any HTTP message body.
        """
        return self.http_method_get(req, False)

    def serve_error(self, type, send_body=True):
        """
        Returns a response of an HTTP error of the given type (e.g. "Not Found")
        """
        #logging.warning("Serving error " + STATUS_CODES[type])

        ret = HTTP_Message()
        body = "<html><body><h1>{}</h1></body></html>".format(STATUS_CODES[type])

        if send_body:
            return ret.create_response(type, body)
        else:
            return ret.create_response(type, None)

    def get_file(self, file_path):
        """
        Returns the contents of the given file as a string
        """
        #logging.info("Retrieving file " + file_path)

        ret = ""
        with open(file_path, 'r') as file:
            ret += file.read()

        return ret

    def get_directory_listing(self, path, uri):
        """
        Returns an HTML message string of the files in the current directory to be used in an HTTP response
        """
        #logging.debug("Generating directory listing for {} ({})".format(uri, path))

        files = [i for i in os.listdir(path) if os.path.isfile(os.path.join(path, i))]
        dirs = [i for i in os.listdir(path) if os.path.isdir(os.path.join(path, i))]

        listing = ""

        for dir in dirs:
            listing += "<p><a href='{}'>{}</a></p>".format(uri + "/" + dir, dir + "/")

        for file in files:
            listing += "<p><a href='{}'>{}</a></p>".format(uri + "/" + file, file)

        body = "<html><body><h1>Index of: {}</h1>{}</body></html>".format(uri, listing)
        return body

    def _get_requests(self, queue):
        while True:
            (clientsocket, _) = self.socket.accept()
            #logging.info("Connected with client " + clientsocket.getsockname()[0])

            data = clientsocket.recv(4096)  # 4096-byte buffer size
            #logging.debug("Received {} bytes of data from client".format(str(len(data))))

            if data:
                queue.put((clientsocket, data))
            else:
                clientsocket.close()

    def _process_requests(self, queue):
        while True:
            if not queue.empty():
                clientsocket, data = queue.get()

                try:
                    request = HTTP_Message(data)
                except HTTPBadRequest:
                    response = self.serve_error("Bad Request")  # Why does Chrome sometimes send empty requests when idle?
                else:
                    response = self.parse_request(request)
                finally:
                    clientsocket.send(response)  # todo: socket.sendfile()
                    #logging.info("Closing connection with " + clientsocket.getsockname()[0])
                    clientsocket.close()

    def run(self):
        request_queue = multiprocessing.Queue(10)

        listener = multiprocessing.Process(target=self._get_requests, args=(request_queue,))
        responder = multiprocessing.Process(target=self._process_requests, args=(request_queue,))

        listener.start()
        responder.start()

        listener.join()
        responder.join()