#!/usr/bin/env python

from __future__ import print_function

import json
import time
import six
import pprint
from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException
from datetime import datetime
from bs4 import BeautifulSoup

with open("config.json") as config:
    CONFIG = json.load(config)

DRIVER = webdriver.Firefox()

START_TIME = datetime.now()
LAST_ADD_ON_CHECK = START_TIME
LAST_UNSHIPPED_CHECK = START_TIME

def print_pucauto():
    """Print logo and version number."""

    print("""
     _______  __   __  _______  _______  __   __  _______  _______
    |       ||  | |  ||       ||   _   ||  | |  ||       ||       |
    |    _  ||  | |  ||       ||  |_|  ||  | |  ||_     _||   _   |
    |   |_| ||  |_|  ||       ||       ||  |_|  |  |   |  |  | |  |
    |    ___||       ||      _||       ||       |  |   |  |  |_|  |
    |   |    |       ||     |_ |   _   ||       |  |   |  |       |
    |___|    |_______||_______||__| |__||_______|  |___|  |_______|
    pucauto.com                                              v0.4.4
    github.com/tomreece/pucauto
    @pucautobot on Twitter

    """)

def debug(str):
    if CONFIG.get("debug"):
        print("DEBUG: ", str)


def wait_for_load():
    """Wait for PucaTrade's loading spinner to dissappear."""

    time.sleep(1)
    while True:
        try:
            loading_spinner = DRIVER.find_element_by_id("fancybox-loading")
        except Exception:
            break


def log_in():
    """Navigate to pucatrade.com and log in using credentials from CONFIG."""

    DRIVER.get("http://www.pucatrade.com")
    home_login_div = DRIVER.find_element_by_id("home-login")
    home_login_div.find_element_by_id("login").send_keys(CONFIG["username"])
    home_login_div.find_element_by_id("password").send_keys(CONFIG["password"])
    home_login_div.find_element_by_class_name("btn-primary").click()


def goto_trades():
    """Go to the /trades page."""

    DRIVER.get("https://pucatrade.com/trades")


def turn_on_auto_matching():
    """Click the toggle on the /trades page to turn on auto matching."""

    DRIVER.find_element_by_css_selector("label.niceToggle").click()


def sort_by_member_points():
    """Click the Member Points table header to sort by member points (desc)."""

    DRIVER.find_element_by_css_selector("th[title='user_points']").click()


def check_runtime():
    """Return True if the main execution loop should continue.

    Selenium and Firefox eat up more and more memory after long periods of
    running so this will stop Pucauto after a certain amount of time. If Pucauto
    was started with the startup.sh script it will automatically restart itself
    again. I typically run my instance for 2 hours between restarts on my 2GB
    RAM cloud server.
    """

    hours_to_run = CONFIG.get("hours_to_run")
    if hours_to_run:
        return (datetime.now() - START_TIME).total_seconds() / 60 / 60 < hours_to_run
    else:
        return True


def full_addon_check_due(interval_minutes):
    """Return True if we should do a FULL check for add on trades."""

    global LAST_ADD_ON_CHECK
    if CONFIG.get("find_add_ons"):
        return (datetime.now() - LAST_ADD_ON_CHECK).total_seconds() / 60 >= interval_minutes
    else:
        return False


def send_card(card, add_on=False):
    """Send a card.

    Args:
    card   - A dictionary with href, name, and value keys
    add_on - True if this card is an add on, False if it's part of a bundle

    Returns True if the card was sent, False otherwise.
    """

    if CONFIG.get("debug"):
        print(u"  DEBUG: Skipping send of '{}'".format(card["name"]))
        return False

    # Go to the /trades/sendcard/******* page first to secure the trade
    DRIVER.get(card["href"])

    try:
        DRIVER.find_element_by_id("confirm-trade-button")
    except Exception:
        # FAILED - output indented for readability w.r.t header/footer messages from elsewhere.
        reason = DRIVER.find_element_by_tag_name("h3").text
        print(u"  Failed to send '{}'. Reason: {}".format(card["name"], reason))
        return False

    # Then go to the /trades/confirm/******* page to confirm the trade
    DRIVER.get(card["href"].replace("sendcard", "confirm"))

    # SUCCESS - output indented for readability w.r.t header/footer messages from elsewhere.
    print(u"  {} '{}' for {} PucaPoints!".format(["Sent","Added"][add_on], card["name"], card["value"]))

    return True


def unshipped_reload_due(interval_minutes):
    """Return True if we should reload unshipped traders list.
    Presumably, we want to do this periodically, especially when we are physically shipping cards.
    """

    global LAST_UNSHIPPED_CHECK
    return (datetime.now() - LAST_UNSHIPPED_CHECK).total_seconds() / 60 >= interval_minutes


def load_unshipped_traders():
    """Build and return a list of members for which we have unshipped cards.
    Will be a dictionary from "trader id" : "trader profile name".
    """

    global LAST_UNSHIPPED_CHECK

    print("Loading unshipped traders...")
    unshipped = dict()

    DRIVER.get("https://pucatrade.com/trades/active")
    
    try:
        DRIVER.find_element_by_css_selector("div.dataTables_filter input").send_keys('Unshipped')
    except NoSuchElementException:
        return unshipped
        
    # Wait a bit for the DOM to update after filtering
    time.sleep(5)
    soup = BeautifulSoup(DRIVER.page_source, "html.parser")
    for trader in soup.find_all("a", class_="trader"):
        debug(pprint.pformat(trader.contents));
        unshipped[trader["href"].replace("/profiles/show/", "")] = trader.contents[0].strip()

    #debug(u"Unshipped Traders List:\n{}".format(pprint.pformat(unshipped)))
    if unshipped:
        print(u"Unshipped Traders List:\n - {}"
              .format("\n - ".join( sorted( map(lambda (k,v): v+" (id: "+k+")", unshipped.iteritems()) ) )))

    LAST_UNSHIPPED_CHECK = datetime.now()
    return unshipped


def load_trade_list(full=False):
    """Scroll to the bottom of the page until we can't scroll any further.
    PucaTrade's trades page implements an infinite scroll table. Without this
    function, we would only see a portion of the cards available for trade.

    Args:
      full - When True, load ALL possible trades; otherwise, only load rows
            above min_value, thus speeding up the search.
    """

    old_scroll_y = 0
    while True:
        debug("Scrolling trades table")
        if not full:
            try:
                lowest_visible_points = int(
                    DRIVER.find_element_by_css_selector(".cards-show tbody tr:last-of-type td.points").text)
                debug("Lowest member points visible in trades table: {}".format(lowest_visible_points))
            except:
                # We reached the bottom
                lowest_visible_points = -1
            if lowest_visible_points < CONFIG["min_value"]:
                # Stop loading because there are no more members with points above min_value
                debug("Curtail loading trades table; lowest: {} <= {} minimum trade.".format(
                    lowest_visible_points, CONFIG["min_value"]))
                break

        DRIVER.execute_script("window.scrollBy(0, 5000);")
        wait_for_load()
        new_scroll_y = DRIVER.execute_script("return window.scrollY;")

        if new_scroll_y == old_scroll_y or new_scroll_y < old_scroll_y:
            break
        else:
            old_scroll_y = new_scroll_y
    debug("Finished scrolling trades table")


def build_trades_dict(soup, unshipped):
    """Iterate through the rows in the table on the /trades page and build up a
    dictionary.

    Args:
    soup - A BeautifulSoup instance of the page DOM

    Returns a dictionary like:

    {
        "1984581": {
            "cards": [
                {
                    "name": "Voice of Resurgence",
                    "value": 2350,
                    "href": https://pucatrade.com/trades/sendcard/38458273
                },
                {
                    "name": "Advent of the Wurm",
                    "value": 56,
                    "href": https://pucatrade.com/trades/sendcard/63524523
                },
                ...
            ],
            "name": "Philip J. Fry",
            "points": 9001,
            "value": 2406
        },
        ...
    }
    """

    trades = {}

    for row in soup.find_all("tr", id=lambda x: x and x.startswith("uc_")):
        member_points = int(row.find("td", class_="points").text)
        member_link = row.find("td", class_="member").find("a", href=lambda x: x and x.startswith("/profiles"))
        member_id = member_link["href"].replace("/profiles/show/", "")
        member_name = member_link.text.strip()
        if (member_id not in unshipped and member_points < CONFIG["min_value"]) :
            # This member isn't possible add on and doesn't have enough points so move on to next row
            continue
        card_name = row.find("a", class_="cl").text
        card_value = int(row.find("td", class_="value").text)
        card_href = "https://pucatrade.com" + row.find("a", class_="fancybox-send").get("href")
        card = {
            "name": card_name,
            "value": card_value,
            "href": card_href
        }
        if member_id in unshipped:
            debug(u"found add-on card for '{}':\n{}".format(member_name,pprint.pformat(card)))
        if trades.get(member_id):
            # Seen this member before in another row so just add another card
            trades[member_id]["cards"].append(card)
            trades[member_id]["value"] += card_value
        else:
            # First time seeing this member so set up the data structure
            trades[member_id] = {
                "cards": [card],
                "name": member_name,
                "points": member_points,
                "value": card_value
            }

    return trades


def find_highest_value_bundle(trades):
    """Find the highest value bundle in the trades dictionary
    with a trade total greater than our minimum threshold.

    Args:
    trades - The result dictionary from build_trades_dict.

    Returns the highest value bundle, which is a tuple of the (k, v) from
    trades, or None.
    """

    if len(trades) == 0:
        return None

    highest_value_bundle = max(six.iteritems(trades), key=lambda x: x[1]["value"])
    #debug(u"Highest value bundle:\n{}".format(pprint.pformat(highest_value_bundle)))

    if highest_value_bundle[1]["value"] >= CONFIG["min_value"]:
        return highest_value_bundle
    else:
        return None


def complete_trades(bundle, add_on=False):
    """Sort the cards by highest value first and then send them all.

    Args:
    bundle - tuple of trades for a single trader.
    add_on - are these add-on trades for an unshipped bundle?

    return the number of cards successfully sent
    """

    if not bundle:
        # No valid bundle was found, give up and restart the main loop
        return 0

    cards = bundle[1]["cards"]
    # Sort the cards by highest value to make the most valuable trades first.
    sorted_cards = sorted(cards, key=lambda k: k["value"], reverse=True)

    member_name = bundle[1]["name"]
    member_points = bundle[1]["points"]
    bundle_value = bundle[1]["value"]
    print(u"Found {}{} card(s) worth {} points to trade to {} who has {} points...".format(
        len(sorted_cards), [""," additional"][add_on],
        bundle_value, member_name, member_points))

    success_count = 0
    success_value = 0
    for card in sorted_cards:
        if send_card(card, add_on):
            success_value += card["value"]
            success_count += 1

    print(u"Successfully {} {} out of {} cards worth {} points!".format(
        ["sent","added"][add_on], success_count, len(sorted_cards), success_value))
    return success_count


def find_add_on_bundles(trades, unshipped):
    """Return subset of 'trades' for which we are have unshipped cards
    to those traders in the 'unshipped' dictionary.
    """

    # interesting syntactic alternatives: http://stackoverflow.com/questions/2844516
    return {id: b for id, b in trades.iteritems() if id in unshipped}


def find_trades(unshipped, full_addon_check=False):
    """The special sauce. Read the docstrings for the individual functions to
    figure out how this works."""

    debug("Looking for bundles...")
    goto_trades()
    wait_for_load()

    # Do a complete check only when we want to and when we have unshipped trades
    if (full_addon_check and len(unshipped) > 0):
        load_trade_list(True)
        debug("Completed FULL serach for add ons; updating timer...")
        global LAST_ADD_ON_CHECK
        LAST_ADD_ON_CHECK = datetime.now()
    else:
        load_trade_list(False)

    soup = BeautifulSoup(DRIVER.page_source, "html.parser")
    trades = build_trades_dict(soup, unshipped)
    # Send higest value bundle, and track recipient in unshipped
    highest_value_bundle = find_highest_value_bundle(trades)
    if highest_value_bundle:
        if complete_trades(highest_value_bundle, highest_value_bundle[0] in unshipped) >= 1:
            unshipped[highest_value_bundle[0]] = highest_value_bundle[1]["name"]
        # remove from the trades dictionary regardless - we've already tried.
        trades.pop(highest_value_bundle[0])
    # Send add-on bundles; this always happens, even if full_addon_check is false.
    for bundle in find_add_on_bundles(trades, unshipped).iteritems():
        debug(u"Add-on bundle found:\n{}".format(pprint.pformat(bundle)))
        complete_trades(bundle, True)


if __name__ == "__main__":
    """Start Pucauto."""

    print_pucauto()

    # sleep for refresh interval (seconds); default: 60; min: 5
    refresh_interval = max(5,CONFIG.get("reload_trades_interval_s") or 60)
    # interval for reloading unshipped traders (minutes); default: 60; min 5
    unshipped_interval = max(5,CONFIG.get("reload_unshipped_interval_m") or 60)
    # interval for chekcing for add-on trades (minutes); default: 20; min 0
    addon_check_interval = max(0.1,CONFIG.get("minutes_between_add_ons_check") or 20)

    print("Logging in...")
    log_in()
    unshipped = load_unshipped_traders()

    print("Loading trades page...")
    goto_trades()
    wait_for_load()

    # Explicit waits to be extra sure auto matching is on because if it's not
    # then bad things happen, like Pucauto sending out cards you don't have.
    # TODO: We could get smarter here and find a way to double check auto
    #   matching really is on, but I don't have a clever solution for it yet, so
    #   this is a band-aid safety measure.
    time.sleep(5)
    print("Turning on auto matching...")
    turn_on_auto_matching()
    time.sleep(5)

    wait_for_load()
    sort_by_member_points()
    wait_for_load()
    print("Finding trades ({} sec interval)...".format(refresh_interval))
    while check_runtime():
        # reload unshipped traders periodically
        if unshipped_reload_due(unshipped_interval):
            unshipped = load_unshipped_traders()
        # find and send trades, and perhaps add-ons
        find_trades(unshipped, full_addon_check_due(addon_check_interval))
        # sleep for refresh interval (seconds)
        time.sleep(refresh_interval)

    DRIVER.close()

