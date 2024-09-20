import os
import finnhub
import csv
from cs50 import SQL
from flask import Flask, flash, redirect, render_template, request, session
from flask_session import Session
from werkzeug.security import check_password_hash, generate_password_hash
from flask import redirect, render_template, request, session
from functools import wraps
import datetime
import creds

# Configure application
app = Flask(__name__)

# Configure session to use filesystem (instead of signed cookies)
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

# Configure CS50 Library to use SQLite database
db = SQL("sqlite:///finance.db")

import finnhub

from flask import redirect, render_template, request, session
from functools import wraps


def apology(message, code=400):
    """Render message as an apology to user."""

    def escape(s):
        """
        Escape special characters.

        https://github.com/jacebrowning/memegen#special-characters
        """
        for old, new in [
            ("-", "--"),
            (" ", "-"),
            ("_", "__"),
            ("?", "~q"),
            ("%", "~p"),
            ("#", "~h"),
            ("/", "~s"),
            ('"', "''"),
        ]:
            s = s.replace(old, new)
        return s

    return render_template("apology.html", top=code, bottom=escape(message)), code


def login_required(f):
    """
    Decorate routes to require login.

    https://flask.palletsprojects.com/en/latest/patterns/viewdecorators/
    """

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get("user_id") is None:
            return redirect("/login")
        return f(*args, **kwargs)

    return decorated_function


def lookup(symbol):
    """Look up quote for symbol."""

    finnhub_client = finnhub.Client(api_key={creds.api_key})
    quote_data = finnhub_client.quote(symbol)
    if quote_data['c'] == 0:
        return None
    return {
        "price": quote_data['c'],
        "symbol": symbol.upper()
    }


def usd(value):
    """Format value as USD."""
    return f"${value:,.2f}"

@app.after_request
def after_request(response):
    """Ensure responses aren't cached"""
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Expires"] = 0
    response.headers["Pragma"] = "no-cache"
    return response


@app.route("/")
@login_required
def index():
    """Show portfolio of stocks"""
    cash = db.execute("SELECT cash FROM users WHERE id = ?", session["user_id"])
    holdings = db.execute("SELECT * FROM holdings WHERE users_id = ?", session["user_id"])

    totalcost = 0
    totalpnl = 0
    for holding in holdings:
        holding['currentprice'] = usd((lookup(holding['symbol']))['price'])
        holding['total'] = ((lookup(holding['symbol']))['price'])*holding['quantity']
        totalcost = totalcost + holding['total']
        holding['pnl'] = holding['total'] - ((holding['average'])*holding['quantity'])
        totalpnl = totalpnl + holding['pnl']

    total = usd(totalcost + cash[0]['cash'])
    cash = usd(cash[0]['cash'])
    return render_template("index.html", cash=cash, holdings=holdings, totalcost=totalcost, total=total, totalpnl=totalpnl)


@app.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    if request.method == "POST":
        newcash = request.form.get("updatecash")
        try:
            newcash = int(newcash)
        except ValueError:
            return apology("Cash must be an integer", 400)
        if int(newcash) < 0:
            return apology("Cash must be a positive", 400)
        db.execute(
            "UPDATE users SET cash = :cash WHERE id = :id", cash=newcash, id=session["user_id"]
        )
        return render_template("settings.html", cash=usd(newcash))
    else:
        cash = db.execute("SELECT cash FROM users WHERE id = ?", session["user_id"])
        return render_template("settings.html", cash=usd(cash[0]['cash']))

@app.route("/updatepassword", methods=["POST"])
@login_required
def updatepassword():

    oldPassword = db.execute("SELECT hash FROM users WHERE id = ?", session["user_id"])
    currentPassword = request.form.get("oldpassword")
    newPassword = request.form.get("newpassword")
    confirmPassword = request.form.get("confirmpassword")

    # Check for user error
    if not currentPassword or not newPassword or not confirmPassword:
        return apology("missing fields")
    if len(newPassword) < 8:
            return apology("password has to be at least 8 characters long", 400)
    elif not check_password_hash(oldPassword[0]["hash"], request.form.get("oldpassword")):
        return apology("invalid current password")
    elif newPassword != confirmPassword:
        return apology("passwords do not match")

    # Generate new password hash
    newPasswordHash = generate_password_hash(newPassword)

    # Update password
    db.execute("UPDATE users SET hash = ? WHERE id = ?", newPasswordHash, session["user_id"])

    flash("Password Changed!")
    return redirect("/")

@app.route("/tobuy", methods=["POST"])
@login_required
def tobuy():
    quote = lookup(request.form.get("symbol"))
    cash = db.execute("SELECT cash FROM users WHERE id = ?", session["user_id"])
    price = quote["price"]
    return render_template("quote.html", cash=round(cash[0]['cash'], 2), quote=quote, price=price)


@app.route("/buy", methods=["POST"])
@login_required
def buy():
    """Buy shares of stock"""
    cash = db.execute("SELECT cash FROM users WHERE id = ?", session["user_id"])
    quote = lookup(request.form.get("symbol"))
    # check if symbol is valid
    if quote == None:
        return apology("must provide valid stock symbol", 400)

    #check if quantiity is valid
    quantity = request.form.get("shares")
    try:
        quantity = int(quantity)
    except ValueError:
        return apology("Quantity must be an integer", 400)
    if quantity < 0:
        return apology("Quantity must be a positive integer", 400)

    #check if user can afford stock
    cost = float(quantity)*(quote["price"])
    if cost > float(cash[0]['cash']):
        return apology("You do not enough cash :( broke boi", 400)

    #deduct cost of shares from user's cash
    cashnow = cash[0]['cash'] - float(cost)
    db.execute(
        "UPDATE users SET cash = :cash WHERE id = :id", cash=cashnow, id=session["user_id"]
    )

    #check if stock already exist in user's holdings.
    #If it does not exist, insert stock into holdings.
    #if it does exist, update new quantity of shares.
    check = db.execute("SELECT symbol FROM holdings WHERE users_id = ? AND symbol = ?",
                        session["user_id"], request.form.get("symbol"))
    if not check:
        #Insert new stock, quantity and average purchase price into holdings db.
        db.execute(
            "INSERT INTO holdings (users_id, symbol, quantity, average) VALUES (?, ?, ?, ?)", session["user_id"], request.form.get(
                "symbol"), quantity, quote["price"]
        )

    else:
        #update quantity and average purchase price into holdings db.
        oldaverage = db.execute("SELECT average FROM holdings WHERE users_id = :id AND symbol = :symbol",
                                id=session["user_id"], symbol=request.form.get("symbol"))
        oldquantity = db.execute("SELECT quantity FROM holdings WHERE users_id = :id AND symbol = :symbol",
                                    id=session["user_id"], symbol=request.form.get("symbol"))
        newaverage = ((oldaverage[0]['average']*oldquantity[0]['quantity']) +
                    cost)/(oldquantity[0]['quantity']+quantity)
        newquantity = oldquantity[0]['quantity'] + quantity
        db.execute(
            "UPDATE holdings SET average = :average, quantity = :quantity WHERE users_id = :id AND symbol = :symbol",
            average=newaverage, quantity=newquantity, id=session["user_id"], symbol=request.form.get(
                "symbol")
        )

    #insert transaction information into history db.
    price = usd(quote["price"])
    db.execute(
        "INSERT INTO history (users_id, symbol, type, quantity, cost, time) VALUES (?, ?, ?, ?, ?, ?)", session["user_id"], request.form.get(
            "symbol"), "BUY", quantity, price, datetime.datetime.now()
    )

    flash("Bought!")
    return redirect("/")



@app.route("/history")
@login_required
def history():
    """Show history of transactions"""
    history = db.execute("SELECT * FROM history WHERE users_id = ?", session["user_id"])
    return render_template("history.html", history=history)


@app.route("/login", methods=["GET", "POST"])
def login():
    """Log user in"""

    # Forget any user_id
    session.clear()

    # User reached route via POST (as by submitting a form via POST)
    if request.method == "POST":
        # Ensure username was submitted
        if not request.form.get("username"):
            return apology("must provide username", 403)

        # Ensure password was submitted
        elif not request.form.get("password"):
            return apology("must provide password", 403)

        # Ensure username and password are at least 6 and 8 characters long respectively
        if len(request.form.get("username")) < 6 or len(request.form.get("password")) < 8:
            return apology("username and password has to be at least 6 and 8 characters long respectively", 400)
            
        # Query database for username
        rows = db.execute(
            "SELECT * FROM users WHERE username = ?", request.form.get("username")
        )

        # Ensure username exists and password is correct
        if len(rows) != 1 or not check_password_hash(
            rows[0]["hash"], request.form.get("password")
        ):
            return apology("invalid username and/or password", 403)

        # Remember which user has logged in
        session["user_id"] = rows[0]["id"]

        #Flask logged in message
        flash("Logged In!")

        # Redirect user to home page
        return redirect("/")

    # User reached route via GET (as by clicking a link or via redirect)
    else:
        return render_template("login.html")


@app.route("/logout")
def logout():
    """Log user out"""

    # Forget any user_id
    session.clear()

    # Redirect user to login form
    return redirect("/")


@app.route("/quote", methods=["GET", "POST"])
@login_required
def quote():
    """Get stock quote."""

    if request.method == "POST":
        # Ensure stock symbol was provided
        if not request.form.get("symbol"):
            return apology("must provide stock symbol", 400)

        quote = lookup(request.form.get("symbol"))

        # Ensure valid stock symbol was provided
        if quote == None:
            return apology("must provide valid stock symbol", 400)
        price = quote["price"]

        # Display current cash holdings
        cash = db.execute("SELECT cash FROM users WHERE id = ?", session["user_id"])
        return render_template("quote.html", cash=round(cash[0]['cash'], 2), quote=quote, price=price)

    else:
        # Display current cash holdings
        cash = db.execute("SELECT cash FROM users WHERE id = ?", session["user_id"])

        # Load popular stock list
        with open('static/stocklist.csv', 'r') as file:
            reader = csv.DictReader(file)
            stocklist = list(reader)
        return render_template("quote.html", cash=round(cash[0]['cash'], 2), stocklist=stocklist)


@app.route("/register", methods=["GET", "POST"])
def register():
    """Register user"""

    if request.method == "POST":
        # Ensure username was submitted
        if not request.form.get("username"):
            return apology("must provide username", 400)

        # Ensure password was submitted
        elif not request.form.get("password"):
            return apology("must provide password", 400)

        # Ensure username and password are at least 6 and 8 characters long respectively
        if len(request.form.get("username")) < 6 or len(request.form.get("password")) < 8:
            return apology("username and password has to be at least 6 and 8 characters long respectively", 400)

        # Query database for username
        rows = db.execute(
            "SELECT * FROM users WHERE username = ?", request.form.get("username")
        )

        # check if username is taken
        if len(rows) == 1:
            return apology("username taken", 400)

        if request.form.get("password") != request.form.get("confirmation"):
            return apology("passwords does not match", 400)

        username = request.form.get("username")
        password = generate_password_hash(request.form.get("password"))

        # insert new user into db
        db.execute(
            "INSERT INTO USERS (username, hash) VALUES (?, ?)", username, password
        )

        rows = db.execute(
            "SELECT * FROM users WHERE username = ?", request.form.get("username")
        )

        # Remember which user has logged in
        session["user_id"] = rows[0]["id"]

        flash("Account Registered!")

        # Redirect user to home page
        return redirect("/")

    # User reached route via GET (as by clicking a link or via redirect)
    else:
        return render_template("register.html")

@app.route("/tosell", methods=["POST"])
@login_required
def tosell():
    """Route user to sell page"""
    symbol = request.form.get("symbol")
    quantity = db.execute(
        "SELECT quantity FROM holdings WHERE users_id = :id AND symbol = :symbol", id=session["user_id"], symbol=symbol)
    return render_template("sell.html", symbol=symbol, quantity=quantity[0]["quantity"])


@app.route("/sell", methods=["POST"])
@login_required
def sell():
    """Sell shares of stock"""
    symbol = request.form.get("symbol")
    quantity = request.form.get("shares")
    quote = lookup(symbol)

    #Check is stock symbol provided is valid
    if quote == None:
        return apology("must provide valid stock symbol", 400)
    try:
        quantity = int(quantity)
    except ValueError:
        return apology("Quantity must be an integer", 400)

    #check if quantity provided is positive
    if quantity < 0:
        return apology("Quantity must be a positive integer", 400)
    currentquantity = db.execute(
        "SELECT quantity FROM holdings WHERE users_id = :id AND symbol = :symbol", id=session["user_id"], symbol=symbol)

    #check if user has enough shares to sell
    if int(currentquantity[0]["quantity"]) < int(quantity):
        return apology("not enough shares to sell", 400)

    #calculate the current value of shares and add into user's cash
    value = float(quantity)*(quote["price"])
    db.execute(
        "UPDATE users SET cash = cash + :value WHERE id = :id", value=value, id=session["user_id"]
    )

    #update new quantity of shares
    db.execute(
        "UPDATE holdings SET quantity = quantity - :quantity WHERE users_id = :id and symbol = :symbol", quantity=quantity, id=session["user_id"], symbol=symbol
    )

    #check if number of shares after selling is 0. Delete stock from holdings database if 0.
    currentquantity = db.execute(
        "SELECT quantity FROM holdings WHERE users_id = :id AND symbol = :symbol", id=session["user_id"], symbol=symbol)
    if int(currentquantity[0]["quantity"]) == 0:
        db.execute(
            "DELETE FROM holdings WHERE users_id = :id AND symbol = :symbol", id=session["user_id"], symbol=symbol
        )

    #Insert transaction information into history db.
    price = usd(quote["price"])
    db.execute(
        "INSERT INTO history (users_id, symbol, type, quantity, cost, time) VALUES (?, ?, ?, ?, ?, ?)", session["user_id"], request.form.get(
            "symbol"), "SELL", quantity, price, datetime.datetime.now()
    )

    flash("Sold!")
    return redirect("/")

