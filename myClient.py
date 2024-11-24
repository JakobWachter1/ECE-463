import time
import sys
import queue
from client import Client
from packet import Packet

class MyClient(Client):
    """Implement a reliable transport using Stop-and-Wait ARQ with debugging statements"""

    def __init__(self, addr, sendFile, recvFile, MSS):
        Client.__init__(self, addr, sendFile, recvFile, MSS)  # initialize superclass
        self.connSetup = 0
        self.connEstablished = 0
        self.connTerminate = 0
        self.sendFile = sendFile
        self.recvFile = recvFile

        # Stop-and-Wait ARQ variables
        self.seqNum = 0               # Sequence number for sender
        self.expectedSeqNum = 0       # Expected sequence number at receiver
        self.timerStart = None        # Start time for retransmission timer
        self.timerInterval = 3        # Timeout interval in seconds
        self.waitingForAck = False    # Flag indicating if sender is waiting for ACK
        self.currentPacket = None     # Packet currently in transit (for retransmission)

    def handleRecvdPackets(self):
        if self.link:
            packet = self.link.recv(self.addr)  # receive a packet from the link
            if packet:
                # Debug: Log received packet
                debug_msg = (f"[{self.addr}] Received Packet - srcAddr: {packet.srcAddr}, dstAddr: {packet.dstAddr}, "
                             f"seqNum: {packet.seqNum}, ackNum: {packet.ackNum}, SYN: {packet.synFlag}, "
                             f"ACK: {packet.ackFlag}, FIN: {packet.finFlag}, Payload Length: {len(packet.payload) if packet.payload else 0}")
                print(debug_msg)
                self.f.write(debug_msg + "\n")

                if self.addr == "A":
                    if packet.synFlag == 1 and packet.ackFlag == 1:
                        if self.connEstablished == 0:
                            print(f"[A] Received SYN-ACK. Sending ACK to establish connection.")
                            ackPacket = Packet("A", "B", 0, 0, 0, 1, 0, None)
                            if self.link:
                                self.link.send(ackPacket, self.addr)
                            self.connEstablished = 1
                            # Reset timers and flags
                            self.waitingForAck = False
                            self.timerStart = None
                            self.currentPacket = None
                        else:
                            print(f"[A] Duplicate SYN-ACK received. Ignoring.")

                    elif packet.finFlag == 1 and packet.ackFlag == 1:
                        print(f"[A] Received FIN-ACK. Sending final ACK to terminate connection.")
                        ackPacket = Packet("A", "B", 0, 0, 0, 1, 0, None)
                        if self.link:
                            self.link.send(ackPacket, self.addr)
                        self.connTerminate = 2  # Indicate termination complete
                        # Reset timers and flags
                        self.waitingForAck = False
                        self.timerStart = None
                        self.currentPacket = None

                    elif packet.ackFlag == 1:
                        print(f"[A] Received ACK with ackNum: {packet.ackNum}. Expected ackNum: {self.seqNum}")
                        if packet.ackNum == self.seqNum:
                            print(f"[A] Correct ACK received for seqNum: {self.seqNum}.")
                            self.seqNum = (self.seqNum + 1) % 2
                            self.waitingForAck = False
                            self.timerStart = None
                            self.currentPacket = None
                        else:
                            print(f"[A] Incorrect ACK received. Ignoring.")

                if self.addr == "B":
                    if packet.synFlag == 1:
                        print(f"[B] Received SYN. Sending SYN-ACK to acknowledge connection setup.")
                        synAckPacket = Packet("B", "A", 0, 0, 1, 1, 0, None)
                        if self.link:
                            self.link.send(synAckPacket, self.addr)
                        self.connSetup = 1

                    elif packet.finFlag == 1:
                        print(f"[B] Received FIN. Sending FIN-ACK to acknowledge connection termination.")
                        finAckPacket = Packet("B", "A", 0, 0, 0, 1, 1, None)
                        if self.link:
                            self.link.send(finAckPacket, self.addr)
                        self.connTerminate = 1

                    elif packet.ackFlag == 0 and packet.synFlag == 0 and packet.finFlag == 0:
                        print(f"[B] Received data packet with seqNum: {packet.seqNum}. Expected seqNum: {self.expectedSeqNum}")
                        if packet.seqNum == self.expectedSeqNum:
                            if packet.payload:
                                self.recvFile.write(packet.payload)
                                print(f"[B] Payload written to recvFile.")
                            # Send ACK with ackNum = packet.seqNum
                            ackPacket = Packet("B", "A", 0, packet.seqNum, 0, 1, 0, None)
                            if self.link:
                                self.link.send(ackPacket, self.addr)
                            print(f"[B] Sent ACK with ackNum: {packet.seqNum}")
                            self.expectedSeqNum = (self.expectedSeqNum + 1) % 2
                        else:
                            print(f"[B] Duplicate packet received. Ignoring payload.")
                            # Resend ACK for last correctly received packet
                            ackNum = (self.expectedSeqNum - 1) % 2
                            ackPacket = Packet("B", "A", 0, ackNum, 0, 1, 0, None)
                            if self.link:
                                self.link.send(ackPacket, self.addr)
                            print(f"[B] Resent ACK with ackNum: {ackNum}")

    def sendPackets(self):
        if self.addr == "A":
            if self.connSetup == 0:
                print(f"[A] Sending SYN to initiate connection.")
                synPacket = Packet("A", "B", 0, 0, 1, 0, 0, None)
                if self.link:
                    self.link.send(synPacket, self.addr)
                self.connSetup = 1
                self.currentPacket = synPacket
                self.waitingForAck = True
                self.timerStart = time.time()

            elif self.connEstablished == 0:
                if self.waitingForAck:
                    elapsed_time = time.time() - self.timerStart if self.timerStart else 0
                    if self.timerStart and elapsed_time > self.timerInterval:
                        print(f"[A] Timeout occurred. Retransmitting SYN packet.")
                        if self.link:
                            self.link.send(self.currentPacket, self.addr)
                        self.timerStart = time.time()

            elif self.connEstablished == 1 and self.connTerminate == 0:
                if not self.waitingForAck:
                    content = self.sendFile.read(self.MSS)
                    if content:
                        print(f"[A] Sending data packet with seqNum: {self.seqNum}")
                        dataPacket = Packet("A", "B", self.seqNum, 0, 0, 0, 0, content)
                        if self.link:
                            self.link.send(dataPacket, self.addr)
                        self.currentPacket = dataPacket
                        self.timerStart = time.time()
                        self.waitingForAck = True
                    else:
                        print(f"[A] No more data. Sending FIN to terminate connection.")
                        finPacket = Packet("A", "B", self.seqNum, 0, 0, 0, 1, None)
                        if self.link:
                            self.link.send(finPacket, self.addr)
                        self.currentPacket = finPacket
                        self.timerStart = time.time()
                        self.waitingForAck = True
                        self.connTerminate = 1
                else:
                    elapsed_time = time.time() - self.timerStart if self.timerStart else 0
                    if self.timerStart and elapsed_time > self.timerInterval:
                        if self.currentPacket:
                            print(f"[A] Timeout occurred. Retransmitting packet with seqNum: {self.currentPacket.seqNum}")
                            if self.link:
                                self.link.send(self.currentPacket, self.addr)
                            self.timerStart = time.time()
                        else:
                            print(f"[A] No current packet to retransmit.")

            elif self.connTerminate == 1:
                if self.waitingForAck:
                    elapsed_time = time.time() - self.timerStart if self.timerStart else 0
                    if self.timerStart and elapsed_time > self.timerInterval:
                        if self.currentPacket:
                            print(f"[A] Timeout occurred. Retransmitting FIN packet.")
                            if self.link:
                                self.link.send(self.currentPacket, self.addr)
                            self.timerStart = time.time()
                        else:
                            print(f"[A] No current packet to retransmit.")
                elif self.connTerminate == 2:
                    print(f"[A] Connection termination complete.")

        if self.addr == "B":
            pass
