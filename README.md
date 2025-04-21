# Chess-Themed Authentication App

A Flask application with user registration, authentication, and a simple chess game API styled with a minimalist chess theme.

## Features

- Chess-themed minimalist user interface
- User registration and authentication
- Session management and security
- REST API for chess games
- Interactive chessboard for playing
- Game matchmaking system

## Setup

1. Install dependencies:
```
pip install -r requirements.txt
```

2. Run the application:
```
python app.py
```

3. Open your browser and navigate to:
```
http://127.0.0.1:5000/
```

## API Endpoints

The application provides the following API endpoints for chess game management:

### JOIN GAME
- **URL**: `/api/join-game`
- **Method**: `POST`
- **Authentication**: Required (session-based)
- **Description**: Finds an opponent or places the user in a queue if no opponents are available
- **Response**:
  - If opponent found: Game details with board state
  - If no opponent: Queued status

### MAKE MOVE
- **URL**: `/api/make-move/<game_id>`
- **Method**: `POST`
- **Authentication**: Required (session-based)
- **Data Params**: `{"from": "e2", "to": "e4"}`
- **Description**: Makes a move in the specified game and returns updated game state
- **Response**: Updated board state and game information

### GAME STATUS
- **URL**: `/api/game-status/<game_id>`
- **Method**: `GET`
- **Authentication**: Required (session-based)
- **Description**: Retrieves the current status of the specified game
- **Response**: Complete game state with board position

## Project Structure

- `app.py`: Main application with routes, models, and game logic
- `templates/`: Chess-themed HTML templates
  - `base.html`: Base template with chess-themed styling
  - `home.html`: Home page with chess game UI
  - `login.html`: Login form
  - `register.html`: Registration form
- `users.db`: SQLite database with user data and chess games 