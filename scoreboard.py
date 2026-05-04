
scores = {}


def update_score(username, score):
    """
    Update a user's score.
    Keeps only the highest score per user.
    """
    try:
        score = int(score)
    except:
        return

    if username not in scores or score > scores[username]:
        scores[username] = score


def get_leaderboard():
    """
    Returns a formatted leaderboard string.
    """
    if not scores:
        return "🏆 Leaderboard is empty"

    sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)

    leaderboard = "🏆 Leaderboard:\n"
    for i, (user, score) in enumerate(sorted_scores, start=1):
        leaderboard += f"{i}. {user}: {score}\n"

    return leaderboard


def reset_scores():
    """
    Optional: clears all scores
    """
    global scores
    scores = {}