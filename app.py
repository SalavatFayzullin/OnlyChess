from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
import os
import json
from datetime import datetime, timedelta
import uuid
from sqlalchemy import inspect, text
import threading
import time

app = Flask(__name__)
app.config['SECRET_KEY'] = os.urandom(24).hex()
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///users.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# User model
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(120), nullable=False)
    games_played = db.Column(db.Integer, default=0)
    games_won = db.Column(db.Integer, default=0)
    games_lost = db.Column(db.Integer, default=0)
    games_drawn = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<User {self.name}>'
        
    def win_rate(self):
        """Calculate win rate as a percentage"""
        if self.games_played == 0:
            return 0
        return round((self.games_won / self.games_played) * 100, 1)
        
    def update_stats(self, game_result):
        """Update user statistics based on game result
        game_result can be 'win', 'loss', or 'draw'
        """
        self.games_played += 1
        if game_result == 'win':
            self.games_won += 1
        elif game_result == 'loss':
            self.games_lost += 1
        elif game_result == 'draw':
            self.games_drawn += 1
        db.session.commit()

def initial_board_state():
    """Create the initial chess board state"""
    return {
        "a8": "black_rook", "b8": "black_knight", "c8": "black_bishop", "d8": "black_queen",
        "e8": "black_king", "f8": "black_bishop", "g8": "black_knight", "h8": "black_rook",
        "a7": "black_pawn", "b7": "black_pawn", "c7": "black_pawn", "d7": "black_pawn",
        "e7": "black_pawn", "f7": "black_pawn", "g7": "black_pawn", "h7": "black_pawn",
        
        "a2": "white_pawn", "b2": "white_pawn", "c2": "white_pawn", "d2": "white_pawn",
        "e2": "white_pawn", "f2": "white_pawn", "g2": "white_pawn", "h2": "white_pawn",
        "a1": "white_rook", "b1": "white_knight", "c1": "white_bishop", "d1": "white_queen",
        "e1": "white_king", "f1": "white_bishop", "g1": "white_knight", "h1": "white_rook"
    }

# Game model
class Game(db.Model):
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    white_player_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    black_player_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    board_state = db.Column(db.Text, nullable=False, default=json.dumps(initial_board_state()))
    current_turn = db.Column(db.String(5), nullable=False, default='white')
    is_finished = db.Column(db.Boolean, default=False)
    winner_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_activity = db.Column(db.DateTime, default=datetime.utcnow)
    timeout_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    
    white_player = db.relationship('User', foreign_keys=[white_player_id])
    black_player = db.relationship('User', foreign_keys=[black_player_id])
    winner = db.relationship('User', foreign_keys=[winner_id])
    timeout_user = db.relationship('User', foreign_keys=[timeout_user_id])
    
    def update_activity(self):
        """Update the last activity timestamp"""
        self.last_activity = datetime.utcnow()
        db.session.commit()
    
    def check_timeout(self):
        """Check if the current player's turn has timed out (1 minute)"""
        if self.is_finished:
            return False
            
        # If last_activity is None, update it and return
        if self.last_activity is None:
            print(f"Game {self.id}: last_activity was None, updating with current time")
            self.last_activity = datetime.utcnow()
            db.session.commit()
            return False
            
        # Calculate time since last activity
        current_time = datetime.utcnow()
        time_since_last_activity = current_time - self.last_activity
        seconds_inactive = time_since_last_activity.total_seconds()
        
        print(f"Game {self.id}: {seconds_inactive:.1f} seconds since last activity. Current turn: {self.current_turn}")
        
        # If more than 1 minute has passed, the player has timed out
        if seconds_inactive > 60:
            print(f"Game {self.id}: TIMEOUT detected after {seconds_inactive:.1f} seconds of inactivity")
            # Determine the winner (opponent of the current player)
            if self.current_turn == 'white':
                self.winner_id = self.black_player_id
                self.timeout_user_id = self.white_player_id
                winner = User.query.get(self.black_player_id)
                loser = User.query.get(self.white_player_id)
            else:
                self.winner_id = self.white_player_id
                self.timeout_user_id = self.black_player_id
                winner = User.query.get(self.white_player_id)
                loser = User.query.get(self.black_player_id)
                
            print(f"Game {self.id}: {winner.name} wins due to {loser.name}'s inactivity")
            self.is_finished = True
            db.session.commit()
            return True
            
        return False

# Queue model to store players waiting for a game
class Queue(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), unique=True, nullable=False)
    joined_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    user = db.relationship('User')

# Move model to store game moves
class Move(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    game_id = db.Column(db.String(36), db.ForeignKey('game.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    from_position = db.Column(db.String(2), nullable=False)
    to_position = db.Column(db.String(2), nullable=False)
    piece = db.Column(db.String(10), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    game = db.relationship('Game')
    user = db.relationship('User')

with app.app_context():
    db.create_all()
    
    # Check and update database schema if needed
    inspector = inspect(db.engine)
    if 'game' in inspector.get_table_names():
        columns = [col['name'] for col in inspector.get_columns('game')]
        
        # Add last_activity column if it doesn't exist
        if 'last_activity' not in columns:
            # Add last_activity column without a default value
            db.session.execute(text("ALTER TABLE game ADD COLUMN last_activity DATETIME"))
            db.session.commit()
            print("Added last_activity column to game table")
            
            # Now update all records with the current timestamp
            current_time = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
            db.session.execute(text(f"UPDATE game SET last_activity = '{current_time}'"))
            db.session.commit()
            print("Updated all games with current timestamp")
        
        # Add timeout_user_id column if it doesn't exist
        if 'timeout_user_id' not in columns:
            db.session.execute(text("ALTER TABLE game ADD COLUMN timeout_user_id INTEGER"))
            db.session.commit()
            print("Added timeout_user_id column to game table")
    
    # Check and update user table for statistics columns
    if 'user' in inspector.get_table_names():
        user_columns = [col['name'] for col in inspector.get_columns('user')]
        
        # Add games_played column if it doesn't exist
        if 'games_played' not in user_columns:
            db.session.execute(text("ALTER TABLE user ADD COLUMN games_played INTEGER DEFAULT 0"))
            db.session.commit()
            print("Added games_played column to user table")
        
        # Add games_won column if it doesn't exist
        if 'games_won' not in user_columns:
            db.session.execute(text("ALTER TABLE user ADD COLUMN games_won INTEGER DEFAULT 0"))
            db.session.commit()
            print("Added games_won column to user table")
        
        # Add games_lost column if it doesn't exist
        if 'games_lost' not in user_columns:
            db.session.execute(text("ALTER TABLE user ADD COLUMN games_lost INTEGER DEFAULT 0"))
            db.session.commit()
            print("Added games_lost column to user table")
        
        # Add games_drawn column if it doesn't exist
        if 'games_drawn' not in user_columns:
            db.session.execute(text("ALTER TABLE user ADD COLUMN games_drawn INTEGER DEFAULT 0"))
            db.session.commit()
            print("Added games_drawn column to user table")
        
        # Add created_at column if it doesn't exist
        if 'created_at' not in user_columns:
            db.session.execute(text("ALTER TABLE user ADD COLUMN created_at DATETIME"))
            db.session.commit()
            
            # Now update all records with the current timestamp
            current_time = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
            db.session.execute(text(f"UPDATE user SET created_at = '{current_time}'"))
            db.session.commit()
            print("Added created_at column to user table")

# Add a background task to check for timeouts
def check_for_timeouts():
    """Background task to periodically check for game timeouts"""
    print("Starting timeout checker background task...")
    while True:
        try:
            with app.app_context():
                # Get all active games
                active_games = Game.query.filter_by(is_finished=False).all()
                print(f"Checking {len(active_games)} active games for timeouts...")
                for game in active_games:
                    # Check for timeout
                    if game.check_timeout():
                        print(f"Game {game.id} timed out - marked as finished")
                        # Update statistics via handle_game_end
                        handle_game_end(game.id, game.winner_id, "timeout")
            
            # Check every 10 seconds
            time.sleep(10)
        except Exception as e:
            print(f"Error in timeout checker: {e}")
            time.sleep(30)  # If there's an error, wait longer before retrying

@app.route('/')
def home():
    if 'user_id' in session:
        user = User.query.get(session['user_id'])
        # Check if user has an active game
        active_game = Game.query.filter(
            (Game.white_player_id == user.id) | (Game.black_player_id == user.id),
            Game.is_finished == False
        ).first()
        
        # Get recent games (both as white and black)
        recent_games = Game.query.filter(
            ((Game.white_player_id == user.id) | (Game.black_player_id == user.id)),
            Game.is_finished == True
        ).order_by(Game.updated_at.desc()).limit(10).all()
        
        # Process game data to display results
        game_history = []
        for game in recent_games:
            game_data = {
                'id': game.id,
                'date': game.updated_at.strftime('%Y-%m-%d %H:%M'),
                'opponent': game.black_player.name if game.white_player_id == user.id else game.white_player.name,
                'player_color': 'white' if game.white_player_id == user.id else 'black',
            }
            
            # Determine game result from user's perspective
            if game.winner_id is None:
                game_data['result'] = 'Draw'
                game_data['result_class'] = 'draw'
            elif game.winner_id == user.id:
                game_data['result'] = 'Win'
                game_data['result_class'] = 'win'
            else:
                game_data['result'] = 'Loss'
                game_data['result_class'] = 'loss'
                
            # Add timeout info if available
            if game.timeout_user_id is not None:
                if game.timeout_user_id == user.id:
                    game_data['timeout'] = 'You timed out'
                else:
                    game_data['timeout'] = 'Opponent timed out'
            
            game_history.append(game_data)
        
        return render_template('home.html', user=user, active_game=active_game, game_history=game_history)
    return render_template('home.html')

@app.route('/leaderboard')
def leaderboard():
    """Display the top 30 players based on win rate and games played"""
    # Get all users with at least 3 games played to avoid skewed stats
    min_games = 3
    users = User.query.filter(User.games_played >= min_games).all()
    
    # Sort users by win rate in descending order
    ranked_users = sorted(users, key=lambda user: user.win_rate(), reverse=True)
    
    # Limit to top 30 players
    top_players = ranked_users[:30]
    
    # Get additional players with games played but not in top 30
    other_users = User.query.filter(User.games_played > 0, User.games_played < min_games).all()
    
    # Sort these by games played in descending order
    other_players = sorted(other_users, key=lambda user: user.games_played, reverse=True)
    
    # Combine the lists with top players first
    all_ranked_players = top_players + other_players[:20]  # Limit other players to 20
    
    # Calculate rank for each player (top players get numeric ranks, others get '-')
    players_with_rank = []
    for idx, player in enumerate(all_ranked_players):
        rank = str(idx + 1) if idx < len(top_players) else '-'
        players_with_rank.append({
            'rank': rank,
            'name': player.name,
            'games_played': player.games_played,
            'wins': player.games_won,
            'losses': player.games_lost,
            'draws': player.games_drawn,
            'win_rate': player.win_rate()
        })
    
    return render_template('leaderboard.html', players=players_with_rank, min_games=min_games)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form['name']
        password = request.form['password']
        
        user_exists = User.query.filter_by(name=name).first()
        if user_exists:
            flash('Username already exists')
            return redirect(url_for('register'))
        
        hashed_password = generate_password_hash(password, method='pbkdf2:sha256')
        new_user = User(name=name, password=hashed_password)
        
        db.session.add(new_user)
        db.session.commit()
        
        flash('Registration successful! Please log in.')
        return redirect(url_for('login'))
    
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        name = request.form['name']
        password = request.form['password']
        
        user = User.query.filter_by(name=name).first()
        
        if not user or not check_password_hash(user.password, password):
            flash('Please check your login details and try again.')
            return redirect(url_for('login'))
        
        session['user_id'] = user.id
        return redirect(url_for('home'))
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    if 'user_id' in session:
        user_id = session['user_id']
        
        # Check if user is in an active game
        active_game = Game.query.filter(
            (Game.white_player_id == user_id) | (Game.black_player_id == user_id),
            Game.is_finished == False
        ).first()
        
        # If user is in an active game, forfeit it
        if active_game:
            # Determine the winner (opponent of the user who logged out)
            winner_id = active_game.black_player_id if active_game.white_player_id == user_id else active_game.white_player_id
            
            # Update game status
            active_game.is_finished = True
            active_game.winner_id = winner_id
            db.session.commit()
    
    # Clear session
    session.pop('user_id', None)
    return redirect(url_for('home'))

# Chess Game API Routes

@app.route('/join-queue', methods=['POST'])
def join_queue():
    if 'user_id' not in session:
        flash('You must be logged in to join a game')
        return redirect(url_for('login'))
    
    user_id = session['user_id']
    
    # Check if user is already in a game
    active_game = Game.query.filter(
        (Game.white_player_id == user_id) | (Game.black_player_id == user_id),
        Game.is_finished == False
    ).first()
    
    if active_game:
        # Redirect to the existing game
        return redirect(url_for('game_page', game_id=active_game.id))
    
    # Check if user is already in queue
    existing_queue = Queue.query.filter_by(user_id=user_id).first()
    if existing_queue:
        # Already in queue, redirect to waiting page
        return redirect(url_for('waiting_page'))
    
    # Find another player in the queue
    opponent = Queue.query.order_by(Queue.joined_at.asc()).first()
    
    if opponent and opponent.user_id != user_id:
        # Match found! Create a game with this player
        opponent_user = User.query.get(opponent.user_id)
        
        # Create a new game
        new_game = Game(
            white_player_id=opponent.user_id,
            black_player_id=user_id
        )
        
        # Remove opponent from queue
        db.session.delete(opponent)
        
        # Also check if current user is in queue (somehow) and remove them too
        current_user_queue = Queue.query.filter_by(user_id=user_id).first()
        if current_user_queue:
            db.session.delete(current_user_queue)
        
        db.session.add(new_game)
        db.session.commit()
        
        # Redirect to game page
        return redirect(url_for('game_page', game_id=new_game.id))
    else:
        # No opponent found, add to queue
        new_queue_entry = Queue(user_id=user_id)
        db.session.add(new_queue_entry)
        db.session.commit()
        
        # Redirect to waiting page
        return redirect(url_for('waiting_page'))

@app.route('/waiting')
def waiting_page():
    if 'user_id' not in session:
        flash('You must be logged in to join a game')
        return redirect(url_for('login'))
    
    user_id = session['user_id']
    
    # Check if user is in queue
    in_queue = Queue.query.filter_by(user_id=user_id).first()
    if not in_queue:
        flash('You are not in the queue')
        return redirect(url_for('home'))
    
    # Check if user has an active game (might have been matched while loading this page)
    active_game = Game.query.filter(
        (Game.white_player_id == user_id) | (Game.black_player_id == user_id),
        Game.is_finished == False
    ).first()
    
    if active_game:
        # Found a game, redirect to it
        return redirect(url_for('game_page', game_id=active_game.id))
    
    # Render the waiting page
    user = User.query.get(user_id)
    return render_template('waiting.html', user=user)

@app.route('/leave-queue', methods=['POST'])
def leave_queue():
    if 'user_id' not in session:
        flash('You must be logged in')
        return redirect(url_for('login'))
    
    user_id = session['user_id']
    
    # Find the user in the queue
    queue_entry = Queue.query.filter_by(user_id=user_id).first()
    
    if queue_entry:
        # Remove from queue
        db.session.delete(queue_entry)
        db.session.commit()
        flash('You have left the queue')
    
    return redirect(url_for('home'))

@app.route('/api/check-status')
def check_status():
    if 'user_id' not in session:
        return jsonify({"error": "You must be logged in"}), 401
    
    user_id = session['user_id']
    
    # Check if user has an active game
    active_game = Game.query.filter(
        (Game.white_player_id == user_id) | (Game.black_player_id == user_id),
        Game.is_finished == False
    ).first()
    
    if active_game:
        # Found a game - make sure user is removed from queue if they're in it
        user_in_queue = Queue.query.filter_by(user_id=user_id).first()
        if user_in_queue:
            db.session.delete(user_in_queue)
            db.session.commit()
        
        your_color = "white" if active_game.white_player_id == user_id else "black"
        opponent_id = active_game.black_player_id if your_color == "white" else active_game.white_player_id
        opponent = User.query.get(opponent_id)
        
        return jsonify({
            "status": "game_started",
            "game_id": active_game.id,
            "your_color": your_color,
            "opponent": opponent.name if opponent else "Unknown Player"
        })
    
    # Check if user is still in queue
    in_queue = Queue.query.filter_by(user_id=user_id).first()
    if in_queue:
        return jsonify({
            "status": "waiting",
            "message": "Still waiting for an opponent"
        })
    
    # User is neither in a game nor in queue
    return jsonify({
        "status": "not_found",
        "message": "You are not in queue or game"
    })

@app.route('/game/<game_id>')
def game_page(game_id):
    if 'user_id' not in session:
        flash('Please login to play', 'error')
        return redirect(url_for('login'))
    
    user_id = session['user_id']
    user = User.query.get(user_id)
    game = Game.query.get(game_id)
    
    if not game:
        flash('Game not found', 'error')
        return redirect(url_for('home'))
    
    if game.white_player_id != user_id and game.black_player_id != user_id:
        flash('You are not a participant in this game', 'error')
        return redirect(url_for('home'))
    
    # Remove user from queue if they're still in it
    user_in_queue = Queue.query.filter_by(user_id=user_id).first()
    if user_in_queue:
        db.session.delete(user_in_queue)
        db.session.commit()
    
    # Check if the game has timed out
    game.check_timeout()
    
    your_color = 'white' if game.white_player_id == user_id else 'black'
    opponent_id = game.black_player_id if your_color == 'white' else game.white_player_id
    opponent = User.query.get(opponent_id)
    
    return render_template('game.html', 
                          game_id=game_id, 
                          your_color=your_color, 
                          opponent=opponent.name,
                          turn=game.current_turn,
                          user=user,
                          is_finished=game.is_finished,
                          winner_id=game.winner_id)

@app.route('/api/game-status/<game_id>', methods=['GET'])
def game_status(game_id):
    if 'user_id' not in session:
        return jsonify({"error": "You must be logged in to view game status"}), 401
    
    user_id = session['user_id']
    game = Game.query.get(game_id)
    
    if not game:
        return jsonify({"error": "Game not found"}), 404
    
    if game.white_player_id != user_id and game.black_player_id != user_id:
        return jsonify({"error": "You are not a participant in this game"}), 403
    
    user_color = "white" if game.white_player_id == user_id else "black"
    opponent_id = game.black_player_id if user_color == "white" else game.white_player_id
    opponent = User.query.get(opponent_id)
    
    board = json.loads(game.board_state)
    
    # Check if the current player is in check
    in_check = is_in_check(game.current_turn, board)
    
    # Get winner information
    winner_name = None
    timeout_info = None
    if game.is_finished and game.winner_id:
        winner = User.query.get(game.winner_id)
        winner_name = winner.name if winner else None
        
        # If game ended due to timeout, include that info
        if game.timeout_user_id:
            timeout_user = User.query.get(game.timeout_user_id)
            if timeout_user:
                timeout_info = f"{timeout_user.name} timed out"
    
    response = {
        "game_id": game.id,
        "your_color": user_color,
        "opponent": opponent.name,
        "board": board,
        "turn": game.current_turn,
        "is_finished": game.is_finished,
        "in_check": in_check,
        "winner": winner_name,
        "timeout_info": timeout_info
    }
    
    return jsonify(response), 200

# Chess rules helper functions
def is_valid_move(piece, from_pos, to_pos, board):
    """
    Check if a move is valid for a given piece according to chess rules
    """
    # Parse positions
    from_col, from_row = from_pos[0], int(from_pos[1])
    to_col, to_row = to_pos[0], int(to_pos[1])
    
    # Get piece color and type
    piece_color, piece_type = piece.split('_')
    
    # Check if destination has a piece of the same color
    if to_pos in board and board[to_pos].startswith(piece_color):
        return False
    
    # Validate based on piece type
    if piece_type == 'pawn':
        return is_valid_pawn_move(piece_color, from_col, from_row, to_col, to_row, board)
    elif piece_type == 'rook':
        return is_valid_rook_move(from_col, from_row, to_col, to_row, board)
    elif piece_type == 'knight':
        return is_valid_knight_move(from_col, from_row, to_col, to_row)
    elif piece_type == 'bishop':
        return is_valid_bishop_move(from_col, from_row, to_col, to_row, board)
    elif piece_type == 'queen':
        return is_valid_queen_move(from_col, from_row, to_col, to_row, board)
    elif piece_type == 'king':
        return is_valid_king_move(from_col, from_row, to_col, to_row)
    
    return False

def is_valid_pawn_move(color, from_col, from_row, to_col, to_row, board):
    """Validate pawn move"""
    # Direction depends on color
    direction = 1 if color == 'white' else -1
    
    # Get column difference and row difference
    col_diff = ord(to_col) - ord(from_col)
    row_diff = to_row - from_row
    
    # Define to_pos here to use throughout the function
    to_pos = to_col + str(to_row)
    
    # Forward move
    if col_diff == 0:
        # Single square forward
        if row_diff == direction:
            return to_pos not in board  # Destination must be empty
        
        # Double square forward from starting position
        if (color == 'white' and from_row == 2 and row_diff == 2) or \
           (color == 'black' and from_row == 7 and row_diff == -2):
            # Check if the path is clear
            middle_row = from_row + direction
            middle_pos = from_col + str(middle_row)
            return middle_pos not in board and to_pos not in board
        
        return False
    
    # Capture move (diagonal)
    if abs(col_diff) == 1 and row_diff == direction:
        # Must capture an opponent's piece
        return to_pos in board and not board[to_pos].startswith(color)
    
    return False

def is_valid_rook_move(from_col, from_row, to_col, to_row, board):
    """Validate rook move"""
    # Rooks move horizontally or vertically
    if from_col != to_col and from_row != to_row:
        return False
    
    # Check if path is clear
    return is_path_clear(from_col, from_row, to_col, to_row, board)

def is_valid_knight_move(from_col, from_row, to_col, to_row):
    """Validate knight move"""
    # Knights move in an L-shape: 2 squares in one direction and 1 square perpendicular
    col_diff = abs(ord(to_col) - ord(from_col))
    row_diff = abs(to_row - from_row)
    
    return (col_diff == 1 and row_diff == 2) or (col_diff == 2 and row_diff == 1)

def is_valid_bishop_move(from_col, from_row, to_col, to_row, board):
    """Validate bishop move"""
    # Bishops move diagonally
    col_diff = abs(ord(to_col) - ord(from_col))
    row_diff = abs(to_row - from_row)
    
    if col_diff != row_diff:
        return False
    
    # Check if path is clear
    return is_path_clear(from_col, from_row, to_col, to_row, board)

def is_valid_queen_move(from_col, from_row, to_col, to_row, board):
    """Validate queen move"""
    # Queens move like rooks or bishops
    col_diff = abs(ord(to_col) - ord(from_col))
    row_diff = abs(to_row - from_row)
    
    # Either straight line or diagonal
    is_straight = from_col == to_col or from_row == to_row
    is_diagonal = col_diff == row_diff
    
    if not (is_straight or is_diagonal):
        return False
    
    # Check if path is clear
    return is_path_clear(from_col, from_row, to_col, to_row, board)

def is_valid_king_move(from_col, from_row, to_col, to_row):
    """Validate king move"""
    # Kings move one square in any direction
    col_diff = abs(ord(to_col) - ord(from_col))
    row_diff = abs(to_row - from_row)
    
    return col_diff <= 1 and row_diff <= 1

def is_path_clear(from_col, from_row, to_col, to_row, board):
    """Check if the path between two positions is clear of pieces"""
    col_diff = ord(to_col) - ord(from_col)
    row_diff = to_row - from_row
    
    # Determine step direction
    col_step = 0 if col_diff == 0 else (1 if col_diff > 0 else -1)
    row_step = 0 if row_diff == 0 else (1 if row_diff > 0 else -1)
    
    # Start from the square after the origin
    current_col = chr(ord(from_col) + col_step)
    current_row = from_row + row_step
    
    # Check each square along the path (excluding destination)
    while (current_col != to_col or current_row != to_row):
        current_pos = current_col + str(current_row)
        if current_pos in board:
            return False  # Path is blocked
        
        # Move to next square
        current_col = chr(ord(current_col) + col_step)
        current_row = current_row + row_step
    
    return True

def find_king_position(color, board):
    """Find the position of a king of the given color on the board"""
    king_piece = f"{color}_king"
    for pos, piece in board.items():
        if piece == king_piece:
            return pos
    return None

def is_in_check(color, board):
    """Check if the king of the given color is in check"""
    # Find the king's position
    king_pos = find_king_position(color, board)
    if not king_pos:
        return False
    
    opponent_color = "black" if color == "white" else "white"
    
    # Check if any opponent's piece can capture the king
    for pos, piece in board.items():
        if piece.startswith(opponent_color):
            if is_valid_move(piece, pos, king_pos, board):
                return True
    
    return False

def is_checkmate(color, board):
    """Check if the king of the given color is in checkmate"""
    # First, check if the king is in check
    if not is_in_check(color, board):
        return False
    
    # Get all pieces of the given color
    pieces = [(pos, piece) for pos, piece in board.items() if piece.startswith(color)]
    
    # Try all possible moves for each piece
    for from_pos, piece in pieces:
        for to_pos in get_all_positions():
            # Skip if the move is invalid
            if not is_valid_move(piece, from_pos, to_pos, board):
                continue
            
            # Test if this move would get the king out of check
            test_board = board.copy()
            test_board[to_pos] = piece
            del test_board[from_pos]
            
            if not is_in_check(color, test_board):
                return False  # Found a move that prevents checkmate
    
    return True

def is_stalemate(color, board):
    """Check if the game is in stalemate for the given color"""
    # The player is not in check but has no legal moves
    if is_in_check(color, board):
        return False
    
    # Get all pieces of the given color
    pieces = [(pos, piece) for pos, piece in board.items() if piece.startswith(color)]
    
    # Try all possible moves for each piece
    for from_pos, piece in pieces:
        for to_pos in get_all_positions():
            # Skip if the move is invalid
            if not is_valid_move(piece, from_pos, to_pos, board):
                continue
            
            # Test if this move wouldn't put the king in check
            test_board = board.copy()
            test_board[to_pos] = piece
            del test_board[from_pos]
            
            if not is_in_check(color, test_board):
                return False  # Found a legal move
    
    return True

def get_all_positions():
    """Generate all possible positions on the chessboard"""
    positions = []
    for col in "abcdefgh":
        for row in range(1, 9):
            positions.append(col + str(row))
    return positions

@app.route('/api/make-move/<game_id>', methods=['POST'])
def make_move(game_id):
    if 'user_id' not in session:
        return jsonify({"error": "You must be logged in to make a move"}), 401
    
    user_id = session['user_id']
    game = Game.query.get(game_id)
    
    if not game:
        return jsonify({"error": "Game not found"}), 404
    
    if game.is_finished:
        return jsonify({"error": "Game is already finished"}), 400
    
    # Check if the game has timed out
    if game.check_timeout():
        return jsonify({"error": "Game has timed out"}), 400
    
    # Get move data from request
    data = request.get_json()
    from_pos = data.get('from')
    to_pos = data.get('to')
    player_name = data.get('name')
    
    if not from_pos or not to_pos or not player_name:
        return jsonify({"error": "Invalid move data. Must include 'from', 'to', and 'name'"}), 400
    
    # Verify player identity
    user = User.query.get(user_id)
    if not user or user.name != player_name:
        return jsonify({"error": "Player name does not match authenticated user"}), 403
    
    # Check if it's the user's turn
    user_color = "white" if game.white_player_id == user_id else "black"
    if user_color != game.current_turn:
        return jsonify({"error": "It's not your turn"}), 400
    
    # Load the current board state
    board = json.loads(game.board_state)
    
    # Check if there's a piece at the from position
    if from_pos not in board:
        return jsonify({"error": "No piece at starting position"}), 400
    
    # Check if the piece belongs to the current player
    piece = board[from_pos]
    if not piece.startswith(user_color):
        return jsonify({"error": "That's not your piece"}), 400
    
    # Validate the move using chess rules
    if not is_valid_move(piece, from_pos, to_pos, board):
        return jsonify({"error": "Invalid move for this piece"}), 400
    
    # Create a copy of the board for testing
    test_board = board.copy()
    test_board[to_pos] = piece
    del test_board[from_pos]
    
    # Check if the move would put or leave the player's king in check
    if is_in_check(user_color, test_board):
        return jsonify({"error": "This move would leave your king in check"}), 400
    
    # Move is valid - update the board
    board[to_pos] = piece
    del board[from_pos]
    
    # Update the game state
    opponent_color = "black" if user_color == "white" else "white"
    game.board_state = json.dumps(board)
    game.current_turn = opponent_color
    
    # Since player made a move, update activity timestamp - THIS IS THE KEY POINT
    # Reset the last_activity timestamp to the current time
    game.last_activity = datetime.utcnow()
    print(f"Game {game.id}: Activity timestamp reset due to player move")
    
    # Record the move
    new_move = Move(
        game_id=game_id,
        user_id=user_id,
        from_position=from_pos,
        to_position=to_pos,
        piece=piece
    )
    
    db.session.add(new_move)
    # Commit the changes to the database
    db.session.commit()
    
    # If the game is now in checkmate or stalemate, update the status
    if is_checkmate(opponent_color, board):
        # Update game status via handle_game_end function
        handle_game_end(game_id, user_id, "checkmate")
        
        return jsonify({
            'status': 'success',
            'board': board,
            'turn': opponent_color,
            'is_finished': True,
            'result': 'checkmate',
            'winner': user.name
        })
        
    if is_stalemate(opponent_color, board):
        # Update game status via handle_game_end function
        handle_game_end(game_id, None, "stalemate")
        
        return jsonify({
            'status': 'success',
            'board': board,
            'turn': opponent_color,
            'is_finished': True,
            'result': 'stalemate',
            'winner': None
        })
    
    response_data = {
        "status": "success",
        "game_id": game_id,
        "board": board,
        "turn": game.current_turn,
        "last_move": {
            "from": from_pos,
            "to": to_pos,
            "piece": piece,
            "player": user_color,
            "player_name": player_name
        },
        "is_finished": game.is_finished
    }
    
    if game.is_finished:
        response_data["result"] = "checkmate" if response_data["result"] == "checkmate" else "stalemate"
    
    return jsonify(response_data), 200

@app.route('/forfeit-game/<game_id>', methods=['POST'])
def forfeit_game(game_id):
    if 'user_id' not in session:
        flash('Please log in to forfeit a game.')
        return redirect(url_for('login'))
    
    user_id = session['user_id']
    game = Game.query.get(game_id)
    
    if not game:
        flash('Game not found.')
        return redirect(url_for('home'))
    
    # Check if user is a participant in the game
    if user_id != game.white_player_id and user_id != game.black_player_id:
        flash('You are not a participant in this game.')
        return redirect(url_for('home'))
    
    # Check if game is already finished
    if game.is_finished:
        flash('This game is already finished.')
        return redirect(url_for('home'))
    
    # User forfeits, opponent wins
    opponent_id = game.black_player_id if user_id == game.white_player_id else game.white_player_id
    
    # Update game status
    game.is_finished = True
    game.winner_id = opponent_id
    
    # Update statistics via handle_game_end
    handle_game_end(game_id, opponent_id, "forfeit")
    
    flash('You have forfeited the game.')
    return redirect(url_for('home'))

@app.route('/api/check-session')
def check_session():
    """API endpoint to check if user's session is still valid"""
    if 'user_id' not in session:
        return jsonify({"error": "Not authenticated"}), 401
    
    return jsonify({"status": "authenticated"}), 200

@app.route('/api/check-timeout/<game_id>')
def check_timeout(game_id):
    """Check if the current player's turn has timed out"""
    if 'user_id' not in session:
        return jsonify({"error": "Not authenticated"}), 401
    
    user_id = session['user_id']
    game = Game.query.get(game_id)
    
    if not game:
        return jsonify({"error": "Game not found"}), 404
    
    if game.white_player_id != user_id and game.black_player_id != user_id:
        return jsonify({"error": "You are not a participant in this game"}), 403
    
    # Check for timeout
    timed_out = game.check_timeout()
    
    # Get user color
    user_color = "white" if game.white_player_id == user_id else "black"
    
    # Build response
    response = {
        "timed_out": timed_out,
        "is_finished": game.is_finished,
        "current_turn": game.current_turn,
        "your_turn": game.current_turn == user_color
    }
    
    if game.is_finished and game.winner_id:
        winner = User.query.get(game.winner_id)
        response["winner"] = winner.name if winner else None
    
    return jsonify(response), 200

@app.route('/api/show-inactivity-status/<game_id>')
def show_inactivity_status(game_id):
    """Show the current inactivity status of a game (for debugging)"""
    if 'user_id' not in session:
        return jsonify({"error": "Not authenticated"}), 401
    
    user_id = session['user_id']
    game = Game.query.get(game_id)
    
    if not game:
        return jsonify({"error": "Game not found"}), 404
    
    if game.white_player_id != user_id and game.black_player_id != user_id:
        return jsonify({"error": "Not your game"}), 403
    
    # Calculate inactivity time
    current_time = datetime.utcnow()
    inactivity_time = None
    
    if game.last_activity:
        time_since_last_activity = current_time - game.last_activity
        inactivity_time = time_since_last_activity.total_seconds()
    
    # Check if the current turn player has been inactive too long
    will_timeout = False
    if inactivity_time and inactivity_time > 60:
        will_timeout = True
    
    return jsonify({
        "game_id": game.id,
        "current_turn": game.current_turn,
        "last_activity": game.last_activity.strftime('%Y-%m-%d %H:%M:%S') if game.last_activity else None,
        "inactivity_time_seconds": inactivity_time,
        "will_timeout": will_timeout,
        "timeout_threshold": 60,
        "remaining_seconds": 60 - inactivity_time if inactivity_time else None
    }), 200

# Update to handle_game_end function to update statistics
def handle_game_end(game_id, winner_id=None, result="checkmate"):
    """Handle game ending with given winner"""
    game = Game.query.get(game_id)
    if not game:
        return False
    
    game.is_finished = True
    game.winner_id = winner_id
    
    # Update player statistics
    white_player = User.query.get(game.white_player_id)
    black_player = User.query.get(game.black_player_id)
    
    if winner_id is None:
        # Game is a draw
        white_player.update_stats('draw')
        black_player.update_stats('draw')
    else:
        # Game has a winner
        if winner_id == white_player.id:
            white_player.update_stats('win')
            black_player.update_stats('loss')
        else:
            white_player.update_stats('loss')
            black_player.update_stats('win')
    
    db.session.commit()
    return True

if __name__ == '__main__':
    # Start the background task in a separate thread
    timeout_thread = threading.Thread(target=check_for_timeouts, daemon=True)
    timeout_thread.start()
    
    app.run(debug=True) 