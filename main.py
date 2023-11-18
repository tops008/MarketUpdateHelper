from PyQt5.QtWidgets import *
from PyQt5.QtGui import QPalette
from PyQt5.QtCore import Qt

from esipy import EsiApp
from esipy import EsiClient
from esipy import EsiSecurity
from esipy import utils

from flask import Flask, request

import os
import functools
import threading
import datetime
import webbrowser
import urllib.request
import json
import math

import CallbackServer

import logging
import datetime


class Character():
    def __init__(self, name="", refresh_token="", auth_token="", character_id=""):
        self.name=name
        self.refresh_token=refresh_token
        self.auth_token=auth_token
        self.character_id=character_id

class EveInterface():

    def __init__(self):
        self.esi_app = EsiApp()
        self.app = self.esi_app.get_latest_swagger
        logging.debug(self.app)
        self.characters={}
        self.stations = {'Jita': 60003760, 'Amarr': 60008494, 'Dodixie': 60011866}
        self.sell_orders={}
        self.sell_prices={}
        self.relist_prices={}
        
        try:
            self.open()
        except FileNotFoundError:
            logging.error("Character file not yet created")
        logging.debug(self.characters)


        try:
            self.open_typeIDs()
        except FileNotFoundError:
            logging.error("typeID file not found")

        load_secret = False
        if load_secret:
            client_id=''
            secret_key=''
            with open('client_secret') as file:
                lines = file.readlines()
                if len(lines) != 2:
                    raise Exception("Can't open client_secret")
            
                client_id = lines[0].strip();
                secret_key = lines[1].strip();

            self.security = EsiSecurity(
                redirect_uri='http://localhost/',
                client_id=client_id,
                #code_verifier=utils.generate_code_verifier(),
                secret_key=secret_key,
                headers={'User-Agent': 'MyHeader'},
            )

                
        else:
            client_id = 'c41bd3b5921d457e93d6456ffb0330d4'
            
            # creating the security object using the app
            self.security = EsiSecurity(
                redirect_uri='http://localhost/',
                client_id=client_id,
                code_verifier=utils.generate_code_verifier(),
                #secret_key=secret_key,
                headers={'User-Agent': 'MyHeader'},
            )
        
        # basic client, for public endpoints only
        self.client = EsiClient(
            security=self.security,
            retry_requests=True,  # set to retry on http 5xx error (default False)
            headers={'User-Agent': 'Something CCP can use to contact you and that define your app'},
            raw_body_only=False,  # default False, set to True to never parse response and only return raw JSON string content.
        )


    def auth(self):

        #start a flask server for the callback url
        thread = threading.Thread(target=CallbackServer.run_server)
        thread.start()
        
        #make sure it's open before we make the auth request
        n_tries = 0
        while CallbackServer.check_server() == 0:
            logging.info(f'Attempt #{n_tries}')
            n_tries += 1
            sleep(0.1)

        logging.info("Server up!")

        #open the browser to auth a character
        url = self.security.get_auth_uri(
            state='SomeRandomGeneratedState',
            scopes=['esi-ui.open_window.v1',
                    'esi-markets.read_character_orders.v1']
        )
        
        logging.debug("Auth url:")
        logging.debug(url)
        webbrowser.open(url)

        #wait for the callback to be sure it's authed
        thread.join()

        #get the auth code
        code = CallbackServer.get_code()
        logging.debug("Found code:")
        logging.debug(code)
        
        #auth and get the refresh token
        token=self.security.auth(code)
        logging.debug("Auth token:")
        logging.debug(token)
        
        refresh_token = token['refresh_token']

        #update the security object, refresh, and verify
        self.security.update_token({'access_token': '',
                                    'expires_in': -1,
                                    'refresh_token': refresh_token})

        token = self.security.refresh()
        logging.debug(f"Token:{token}")
        
        api_info = self.security.verify(options={'verify_aud':False})
        logging.debug(f"API Info:{api_info}")

        name=api_info['name']
        character_id=api_info['sub'].split(':')[2]
        
        #put the character in the dict
        self.characters[name] = Character(name=name,
                                          refresh_token=refresh_token,
                                          auth_token=code,
                                          character_id=character_id)
        
        #save the current character states
        self.save()

        #return the name of the character
        return name
            
    #refresh the auth token
    def refresh(self, name):

        refresh_token = self.characters[name].refresh_token
        self.security.update_token({'access_token': '',
                                    'expires_in': -1,
                                    'refresh_token': refresh_token})

        
        tokens = self.security.refresh()
        logging.debug(tokens)
        
        api_info = self.security.verify(options={'verify_aud':False})
        logging.debug(api_info)
        self.characters[name].character_id=api_info['sub'].split(':')[2]

        self.save()

    #save character state and tokens to file
    def save(self):
        with open('characters.txt','w') as file:
            for char in self.characters.values():
                file.write('\t'.join([char.name,
                                      char.auth_token,
                                      char.refresh_token,
                                      char.character_id+'\n']))

    #read character state and tokens from file
    def open(self):
        with open('characters.txt') as file:
            lines = file.readlines()
            for line in lines:
                eles = line.split('\t')
                if len(eles) != 4:
                    continue
                name=eles[0]
                auth_token=eles[1]
                refresh_token=eles[2]
                character_id=eles[3]

                self.characters[name] = Character(name=name,
                                                  auth_token=auth_token,
                                                  refresh_token=refresh_token,
                                                  character_id=character_id)

    def open_typeIDs(self):
        self.typeid_to_name={}
        self.name_to_typeid={}
        with open('typeids.txt',encoding='utf-8') as file:
            lines = file.readlines()
            for line in lines:
                eles = line.split('\t')
                if len(eles) != 2:
                    continue
                type_id = eles[1].strip()
                name = eles[0].strip()
                self.typeid_to_name[int(type_id)] = name
                self.name_to_typeid[name] = int(type_id)
        logging.debug(self.typeid_to_name)
                

    def update_sell_orders(self, character_name, station_name="", deltaT=0):
        char = self.characters[character_name]
        station_id = self.stations[station_name]
        self.refresh(character_name)
        market_order_operation = self.app.op['get_characters_character_id_orders'](character_id=char.character_id)
        
        # do the request
        response = self.client.request(market_order_operation)
        logging.debug(response.data)

        self.sell_orders[character_name] = {}
        current_time = datetime.datetime.now(datetime.timezone.utc)
        if len(response.data) > 0:
            logging.debug(str(response.data[0].issued))
        else:
            logging.debug('no market orders found')
            
        recently_updated = set()
        for i in range(len(response.data)):
            if response.data[i].location_id != station_id and station_id != 0: continue
            
            issued_time=datetime.datetime.fromisoformat(str(response.data[i].issued))

            type_id = response.data[i].type_id
            
            if (current_time-issued_time).total_seconds()/60./60. < deltaT:
                recently_updated.add(type_id)
                continue

            price = response.data[i].price
            n = response.data[i].volume_remain

            if int(type_id) not in self.typeid_to_name: continue
            
            if type_id not in self.sell_orders[character_name]:
                self.sell_orders[character_name][type_id] = {'price':price, 'n':n}
            else:
                self.sell_orders[character_name][type_id]['n'] += n
                self.sell_orders[character_name][type_id]['price'] = min(price,
                                                                         self.sell_orders[character_name][type_id]['price'])

        logging.debug(self.sell_orders[character_name])
        logging.debug(recently_updated)
        self.sell_orders[character_name] = {k: v for k, v in self.sell_orders[character_name].items() if k not in recently_updated}

        logging.debug(self.sell_orders[character_name])
        
    def update_sell_prices(self, character_name, station_name):
        station_id = str(self.stations[station_name])
        base_url="https://market.fuzzwork.co.uk/aggregates/?station="+station_id+"&types="
        type_ids = ','.join(map(str, list(self.sell_orders[character_name].keys())))
        url=base_url+type_ids
        response = urllib.request.urlopen(url)
        if response.code != 200:
            raise InvalidResponse("Response code "+str(response.code))
        
        logging.debug(response)

        prices = json.loads(response.read().decode('utf-8'))
        logging.debug(prices)

        
        
        self.sell_prices[station_name] = {}
        if prices != []:
            for type_id in prices.keys():
                self.sell_prices[station_name][int(type_id)] = prices[type_id]['sell']['min']

        logging.debug(self.sell_prices[station_name])

        
    def update_relist_prices(self, character_name, station_name, type_ids):
        station_id = str(self.stations[station_name])
        base_url="https://market.fuzzwork.co.uk/aggregates/?station="+station_id+"&types="
        type_ids = ','.join(map(str, type_ids))
        url=base_url+type_ids
        response = urllib.request.urlopen(url)
        if response.code != 200:
            raise InvalidResponse("Response code "+str(response.code))
        
        logging.debug(response)

        prices = json.loads(response.read().decode('utf-8'))
        logging.debug(prices)

        
        
        self.relist_prices[station_name] = {}
        if prices != []:
            for type_id in prices.keys():
                self.relist_prices[station_name][int(type_id)] = prices[type_id]['sell']['min']

        logging.debug(self.relist_prices[station_name])        

    def open_ui(self, character_name, type_id):
        self.refresh(character_name)
        open_window = self.app.op['post_ui_openwindow_marketdetails'](type_id=type_id,)
        response = self.client.request(open_window)
        
class Window(QMainWindow):

    def __init__(self):
        super().__init__()

        self.setWindowFlags(Qt.WindowStaysOnTopHint)
        self.buttons = {}
        
        #initialize variables
        self.deltaT=0
        self.relistSpacing=1
        self.eve_interface = EveInterface()

        self.makeTabs()
        
        self.setCentralWidget(self.tabs)
        #self.setCentralWidget(self.scrollBar)
        #self.setCentralWidget(self.centralWidget)

        #set meta info
        self.setWindowTitle("Market Update Helper")
        
        #create main window objects
        self._createMenu()
        #self._createToolBar()
        self._createStatusBar()

        try:
            self.loadSettings()
        except FileNotFoundError:
            pass
            
    def loadSettings(self):
        self.options = {}
        with open('settings.txt') as file:
            lines = file.readlines()
            for line in lines:
                eles = line.split('\t')
                if len(eles) != 2: continue
                name=eles[0]
                value=eles[1]

                if name == 'relist spacing':
                    self.relistSpacing = int(value)


    def saveSettings(self):
        with open('settings.txt','w') as file:
            file.write('\t'.join(['relist spacing', str(self.relistSpacing)+'\n']))


    def closeEvent(self, event):
        self.saveSettings()
        
    #main window objects
    def _createMenu(self):
        self.menu = self.menuBar().addMenu("&Menu")
        self.menu.addAction('&Auth', self.auth)
        self.menu.addAction('&Exit', self.close)

    def _createToolBar(self):
        tools = QToolBar()
        self.addToolBar(tools)
        tools.addAction('Exit', self.close)

    def _createStatusBar(self):
        status = QStatusBar()
        status.showMessage("I'm the Status Bar")
        self.setStatusBar(status)

    #signals
    def updateItems(self):
        char_name = self.charSelectBox.currentText()
        station_name = self.stationSelectBox.currentText()
        #update the list of sell orders and min buy prices in the station
        self.eve_interface.update_sell_orders(char_name,
                                              station_name,
                                              int(self.deltaT))
        self.eve_interface.update_sell_prices(char_name,
                                              station_name)

        #clear the existing item widgets in the grid layout 
        for row in range(self.gridItemsPos, self.mainGrid.rowCount()):
            for col in range(self.mainGrid.columnCount()):
                item = self.mainGrid.itemAtPosition(row, col)
                if item is not None:
                    item.widget().deleteLater()
                    self.mainGrid.removeItem(item)


        #add the new items
        self.items = {}
        type_ids = list(self.eve_interface.sell_orders[char_name].keys())
        for type_id in type_ids:
            name = self.eve_interface.typeid_to_name[type_id]
            new_price = float(self.eve_interface.sell_prices[station_name][type_id])
            old_price = float(self.eve_interface.sell_orders[char_name][type_id]['price'])
            if old_price <= new_price: continue;
            if new_price > 0:
                new_price = new_price-2*pow(10,math.ceil(math.log(new_price,10))-4)

            self.items[name] = (new_price, type_id)
                
        self.add_items()
        
    def add_items(self):
        self.buttons['update'] = {}
        row = self.gridItemsPos
        sorted_item_names = list(self.items.keys())
        sorted_item_names.sort()
        
        for name in sorted_item_names:
            k = name
            v = self.items[k]
            for i in range(1):
                self.mainGrid.addWidget(QLabel(k),row,0)
                self.mainGrid.addWidget(QLabel(str(v[0])),row,1)
                button = QPushButton("Open")
                button.clicked.connect(functools.partial(self.open_and_copy, 'update', k, v[0], v[1]))
                self.buttons['update'][k] = button
                self.mainGrid.addWidget(self.buttons['update'][k],row,2)
                row += 1

    def changeCharacter(self):
        pass

    def changeDeltaT(self):
        self.deltaT = self.deltaTSlider.value()
        self.sliderLabel.setText(str(self.deltaT)+"H")

    def changeRelistSpacing(self):
        self.relistSpacing = self.spacingSlider.value()
        self.relistGrid.setVerticalSpacing(self.relistSpacing)
        
    def open_and_copy(self, button_group, name, price, type_id):
        QApplication.clipboard().setText(str(price))
        palette = QPalette()
        palette.setColor(QPalette.ButtonText, Qt.red)
        self.buttons[button_group][name].setPalette(palette)

        self.eve_interface.open_ui(self.charSelectBox.currentText(), type_id)
        

    def auth(self):
        name = self.eve_interface.auth()
        if self.charSelectBox.findText(name) == -1:
            self.charSelectBox.addItem(name)
    
    def refresh_current(self):
        currentChar=self.charSelectBox.currentText()
        self.eve_interface.refresh(currentChar)

    def clearRelistData(self):
        self.relister.textField.setPlainText("")
        
    def importRelistData(self):
        self.relistData = {}
        text = self.relister.textField.toPlainText()

        type_ids_to_retrieve = []
        for line in text.split('\n'):
            eles = line.split('\t')
            if len(eles) == 0: continue
            name=eles[0]
            if len(eles) == 1:
                price = 0
                try:
                    type_ids_to_retrieve.append(self.eve_interface.name_to_typeid[name])
                except KeyError:
                    logging.debug(f'Unknown relist type name: {name}')
            else:
                price=float(eles[1].replace('$','').replace(',',''))
                
            self.relistData[name] = price

        if type_ids_to_retrieve != []:
            station_name = self.stationSelectBox.currentText()
            self.eve_interface.update_relist_prices(self.charSelectBox.currentText(), station_name, type_ids_to_retrieve)
            for type_id in type_ids_to_retrieve:
                name = self.eve_interface.typeid_to_name[type_id]
                new_price = float(self.eve_interface.relist_prices[station_name][int(type_id)])
                if new_price > 0:
                    new_price = new_price-2*pow(10,math.ceil(math.log(new_price,10))-4)
                self.relistData[name] = new_price
            
        
            
        logging.debug(self.relistData)

        self.buttons['relist'] = {}
        self.relistGrid = QGridLayout()
        row=0

        #add slider for vertical spacing
        self.relistGrid.setVerticalSpacing(self.relistSpacing)


        #need to sort by lower case names, since python ranks upper case higher than any other lower case letter
        lower_to_standard_names = {}
        for item in self.relistData.keys(): lower_to_standard_names[item.lower()] = item
        
        sorted_item_names = [item.lower() for item in list(self.relistData.keys())]
        sorted_item_names.sort()
        for item in sorted_item_names:
            name = lower_to_standard_names[item]
            price = self.relistData[name]
            type_id = self.eve_interface.name_to_typeid[name]
            for i in range(1):
                self.relistGrid.addWidget(QLabel(name),row,0)
                self.relistGrid.addWidget(QLabel(str(price)),row,1)
                button = QPushButton("Open")
                button.clicked.connect(functools.partial(self.open_and_copy, 'relist', name, price, type_id))
                self.buttons['relist'][name] = button
                self.relistGrid.addWidget(self.buttons['relist'][name],row,2)
                row += 1

        self.relistWindow=QMainWindow()
        relistWidget = QWidget()
        relistWidget.setLayout(self.relistGrid)
        scrollBar = QScrollArea()
        scrollBar.setWidgetResizable(True)
        scrollBar.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scrollBar.setWidget(relistWidget)
        self.relistWindow.setCentralWidget(scrollBar)
        self.relistWindow.setWindowFlags(Qt.WindowStaysOnTopHint)

        tools = QToolBar()
        self.relistWindow.addToolBar(tools)
        tools.addAction('Exit', self.relistWindow.close)
        tools.addAction('Resize', self.openResizeWindow)

        self.relistWindow.show()

    def openResizeWindow(self):
        self.spacingSlider = QSlider(Qt.Horizontal)
        self.spacingSlider.setMinimum(0)
        self.spacingSlider.setMaximum(30)
        self.spacingSlider.setSingleStep(1)
        self.spacingSlider.setTickInterval(1)
        self.spacingSlider.setTickPosition(QSlider.TicksBothSides)
        self.spacingSlider.setValue(self.relistSpacing)
        self.spacingSlider.valueChanged.connect(self.changeRelistSpacing)
        
        self.resizeWindow = QMainWindow()
        self.resizeWindow.setCentralWidget(self.spacingSlider)
        self.resizeWindow.resize(200,50)
        self.resizeWindow.setWindowFlags(Qt.WindowStaysOnTopHint)
        self.resizeWindow.show()
        
    #widget creator handles
    def makeTabs(self):
        #put everything into tabs
        self.tabs = QTabWidget()
        self.makeUpdater()
        self.tabs.addTab(self.scrollBar, "Update")

        self.makeRelister()
        self.tabs.addTab(self.relister, "Relist")

    def makeRelister(self):
        #add 2 widgets: import button and text box
        self.relister = QWidget()
        self.relister.layout = QVBoxLayout()

        #make import button
        relistButtons = QWidget()
        relistButtons.layout = QHBoxLayout()
        importButton = QPushButton("Import")
        importButton.clicked.connect(self.importRelistData)
        relistButtons.layout.addWidget(importButton)
        clearButton = QPushButton("Clear")
        clearButton.clicked.connect(self.clearRelistData)
        relistButtons.layout.addWidget(clearButton)
        relistButtons.setLayout(relistButtons.layout)
        self.relister.layout.addWidget(relistButtons)        
        
        #make text box
        self.relister.textField = QPlainTextEdit("")
        self.relister.layout.addWidget(self.relister.textField)

        #set layout
        self.relister.setLayout(self.relister.layout)

    def makeUpdater(self):
        #create main grid
        self.makeMainGrid()

        #test
        self.updater = QWidget()
        self.updater.setLayout(self.mainGrid)

        self.scrollBar = QScrollArea()
        self.scrollBar.setWidgetResizable(True)
        self.scrollBar.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scrollBar.setWidget(self.updater)

    def makeMainGrid(self):
        self.mainGrid = QGridLayout()

        row=0
        self.makeTopRow()
        self.mainGrid.addLayout(self.topRow, row, 0, 1, 3)
        row += 1
        
        #add auth and refresh buttons for testing
        #self.makeTestRow()
        #self.mainGrid.addLayout(self.testRow, row, 0, 1, 3)
        #row += 1
        
        #add the labels of the grid columns
        self.mainGrid.addWidget(QLabel("Item"),row,0)
        self.mainGrid.addWidget(QLabel("Price"),row,1)
        self.mainGrid.addWidget(QLabel("Execute"),row,2)
        row += 1

        self.gridItemsPos=row
        #add example items
        self.items = {"Tritanium": (9.1, 34)}
        self.add_items()
            
    def makeTopRow(self):
        #make the top row of buttons
        self.topRow = QHBoxLayout()
        self.makeCharSelectBox()
        self.topRow.addWidget(self.charSelectBox)

        self.makeStationSelectBox()
        self.topRow.addWidget(self.stationSelectBox)
        
        self.makeDeltaTSlider()
        self.topRow.addWidget(self.deltaTSlider)
        self.topRow.addWidget(self.sliderLabel)

        self.makeUpdateButton()
        self.topRow.addWidget(self.updateButton)

    def makeTestRow(self):
        self.testRow = QHBoxLayout()
        authButton = QPushButton("Auth")
        authButton.clicked.connect(self.auth)
        self.testRow.addWidget(authButton)

        refreshButton = QPushButton("Refresh")
        refreshButton.clicked.connect(self.refresh_current)
        self.testRow.addWidget(refreshButton)

    def makeCharSelectBox(self):
        #add the character drop-down box
        self.charSelectBox = QComboBox()
        charNames = list(self.eve_interface.characters.keys())
        charNames.sort()
        for name in charNames:
            self.charSelectBox.addItem(name)
            
        #self.charSelectBox.addItem("Production Clone 0")
        #self.charSelectBox.addItem("Endymion Risen")
        #self.charSelectBox.addItem("Russ Nuwater")
        self.charSelectBox.activated.connect(self.changeCharacter)

    def makeStationSelectBox(self):
        #add the character drop-down box
        self.stationSelectBox = QComboBox()
        stations = list(self.eve_interface.stations.keys())
        stations.sort()
        for station in stations:
            self.stationSelectBox.addItem(station)
        
        
    def makeDeltaTSlider(self):
        #add delta T slider
        self.deltaTSlider = QSlider(Qt.Horizontal)
        self.deltaTSlider.setMinimum(0)
        self.deltaTSlider.setMaximum(48)
        self.deltaTSlider.setSingleStep(1)
        self.deltaTSlider.setTickInterval(1)
        self.deltaTSlider.setTickPosition(QSlider.TicksBothSides)
        self.deltaTSlider.setValue(self.deltaT)
        self.deltaTSlider.valueChanged.connect(self.changeDeltaT)

        #add text area to show value of slider
        self.sliderLabel = QLabel()
        self.sliderLabel.setText(str(self.deltaTSlider.value())+"H")

    def makeUpdateButton(self):
        #add the main 'update' button
        self.updateButton = QPushButton("Update")
        self.updateButton.clicked.connect(self.updateItems)


def main():

    currenttime = datetime.datetime.now().strftime('%Y.%m.%d.%H.%M.%S')
    os.makedirs('log', exist_ok=True)
    logging.basicConfig(filename=f'log/{currenttime}.debug',
                        encoding='utf-8',
                        level=logging.DEBUG)
    logging.info('Starting application')
    app = QApplication([])

    window = Window()
    window.show()
    
    app.exec_()


if __name__ == "__main__":
    main()

