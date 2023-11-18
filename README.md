# MarketUpdateHelper

- Menu -> Auth for each character you want to use.
- Authentication data is stored in the characters.txt, which is stored and created where the app is executed from.
- Runtime logs are saved in the 'log' folder.

# Update tool

- Open the 'Update' tab.
- Select character and location, and select the update time threshold with the slider. Market orders with age less than this will be ignored. 
- Click 'Update' to get a list of qualifying open orders below.
- Click 'Open' next to each to open the market window for this order.
- The next-lowest market price will be copied to your clipboard. You can then update your market order and paste this price into the window.
- Data for station market orders are pulled from market.fuzzwork.co.uk API and aren't perfectly live, so there may be a small delay between current and buffered prices.

# Relist tool

- Select character from the 'Update' tab.
- Open the 'Relist' tab.
- Copy into the open field tab-separated data consisting of two columns, where the first column is the item name, and the second column is the price you'd like to list the item for
- Alternatively, you can copy a single column of data with the item name, and the price will be pulled from the market.fuzzwork.co.uk API
- You can also mix and match 1- and 2-column data. Additional columns are ignored.
- Click 'Import' to open a pop-up window with buttons that interface with the Eve API for the selected character.
- You can adjust the spacing between lines with the 'Resize' button in the popup menu so that the spacing corresponds with your multisell window, which can vary based on your resolution.
