import json
import random
import re
import cerberus

from bottle import (
    Bottle, Route, run, request, response, abort
)
from datetime import datetime, timedelta
from math import ceil
from pony import orm
from redis import Redis
from rq_scheduler import Scheduler
from uuid import UUID, uuid4

r = Redis(host='localhost', port=6379, db=0, decode_responses=True)
scheduler = Scheduler(connection=Redis(host='localhost', port=6379, db=1))
db = orm.Database()


class UUIDEncoder(json.JSONEncoder):

    def default(self, obj):
        if isinstance(obj, UUID):
            return str(obj)
        return super().default(obj)


class Validator(cerberus.Validator):

    def _validate_is_uuid(self, is_uuid, field, value):
        re_uuid = re.compile(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}', re.I)
        if is_uuid and not re_uuid.match(value):
            self._error(f"Value for field '{field}' must be valid UUID")


def get_object_or_404(cls, **kwargs):
    obj = cls.get(**kwargs)
    if obj is None:
        abort(404, f'`{cls.__name__}` object not found')
    return obj


class GetMixin:

    @classmethod
    def get_or_create(cls, **kwargs):
        r = cls.get(**kwargs)
        if r is None:
            return cls(**kwargs), True
        else:
            return r, False


class Player(db.Entity):
    _table_ = 'Players'
    id = orm.PrimaryKey(UUID)
    name = orm.Required(str)
    power = orm.Required(int)
    medals = orm.Required(int)
    money = orm.Required(int)
    tournaments = orm.Set('Tournament')
    groups = orm.Set('Group')
    attacks = orm.Set('Attack')
    attacked_by = orm.Set('Attack')


class Tournament(db.Entity):
    _table_ = 'Tournaments'
    start_timestamp = orm.Required(datetime)
    end_timestamp = orm.Required(datetime)
    players = orm.Set('Player')
    groups = orm.Set('Group')
    attacks = orm.Set('Attack')

    @property
    def started(self):
        return self.start_timestamp <= datetime.now() < self.end_timestamp

    @property
    def finished(self):
        return self.end_timestamp <= datetime.now()


class Group(db.Entity):
    _table_ = 'Groups'
    tournament = orm.Required(Tournament)
    players = orm.Set(Player)


class Attack(db.Entity, GetMixin):
    _table_ = 'Attacks'
    tournament = orm.Required(Tournament)
    from_player = orm.Required(Player, reverse='attacks')
    to_player = orm.Required(Player, reverse='attacked_by')


def start_tournament(id: int, group_size: int) -> None:
    with orm.db_session:
        tournament = Tournament[id]
        players = tournament.players.order_by(orm.desc(Player.power))
        pages = ceil(tournament.players.count() / group_size)
        for page in range(1, pages + 1):
            Group(tournament=tournament, players=players.page(page, pagesize=group_size))


def rewarding_players(id: int) -> None:
    with orm.db_session:
        tournament = Tournament[id]
        for group in tournament.groups:
            winners = group.players.order_by(orm.desc(Player.medals))[:3]
            for place, winner in enumerate(winners):
                winner.money += [300, 200, 100][place]


@orm.db_session
def create_player():
    validator = Validator({
        'name': {'type': 'string', 'empty': False, 'required': True},
        'power': {'type': 'integer', 'required': True, 'min': 1, 'max': 1000},
        'medals': {'type': 'integer', 'required': False, 'min': 0, 'default': 0},
        'money': {'type': 'integer', 'required': False, 'min': 0, 'default': 1000},
    })
    is_valid = validator.validate(request.json)
    if not is_valid:
        abort(400, validator.errors)

    id = uuid4()
    player = Player(id=id, **validator.document)
    response.status = 201
    return {'id': str(player.id)}


@orm.db_session
def player_detail(id):
    player = get_object_or_404(Player, id=id)
    return player.to_dict(['name', 'power', 'medals', 'money'])


@orm.db_session
def create_tournament():
    to_datetime = lambda s: datetime.strptime(s, '%Y-%m-%dT%H:%M:%S')
    validator = Validator({
        'start_timestamp': {
            'type': 'datetime',
            'empty': False,
            'required': True,
            'coerce': to_datetime
        },
        'end_timestamp': {
            'type': 'datetime',
            'empty': False,
            'required': True,
            'coerce': to_datetime
        },
    })
    is_valid = validator.validate(request.json)
    if not is_valid:
        abort(400, validator.errors)

    tournament = Tournament(**validator.document)
    orm.commit()

    # Schedule tournament
    # TODO: Validate delay
    delay = tournament.start_timestamp - datetime.now()
    scheduler.enqueue_in(
        delay,
        start_tournament,
        tournament.id,
        request.app.config['TOURNAMENT_GROUP_SIZE']
    )

    # threading.Thread(
    #     target=start_tournament,
    #     args=(delay.seconds, tournament.id, request.app.config['TOURNAMENT_GROUP_SIZE']),
    #     daemon=True
    # ).start()

    delay = tournament.end_timestamp - datetime.now()
    scheduler.enqueue_in(
        delay,
        rewarding_players,
        tournament.id,
    )

    response.status = 201
    return {'id': tournament.id}


@orm.db_session
def tournament_detail(id):
    tournament = get_object_or_404(Tournament, id=id)

    # TODO: There are should be more conviniet and pythonic way
    groups = {}
    for group in tournament.groups:
        groups[group.id] = [
            player.to_dict(['id', 'name', 'power', 'medals', 'money'])
            for player in group.players.order_by(orm.desc(Player.medals))
        ]

    response.set_header('Content-Type', 'application/json')
    return json.dumps(groups, cls=UUIDEncoder)


@orm.db_session
def participate(id):
    validator = Validator({
        'player_id': {
            'is_uuid': True,
            'type': 'string',
            'empty': False,
            'required': True
        }
    })
    is_valid = validator.validate(request.json)
    if not is_valid:
        abort(400, validator.errors)

    tournament = get_object_or_404(Tournament, id=id)
    if tournament.finished:
        abort(403, 'The tournament has ended')
    if tournament.started:
        abort(403, 'The tournament has already begun')

    player_id = validator.document['player_id']
    player = get_object_or_404(Player, id=player_id)

    if tournament.players.count() == request.app.config['TOURNAMENT_MAX_PLAYERS']:
        abort(403, 'Exceed maximum number of players')

    if player in tournament.players:
        abort(403, 'Player already participate in this tournament')

    tournament.players.add(player)
    response.status = 201
    return {}


@orm.db_session
def get_opponent(id, player_id):
    tournament = get_object_or_404(Tournament, id=id)
    player = get_object_or_404(Player, id=player_id)

    # TODO: Read pony docs about queries
    player_attacks = orm.select(
        attack.to_player for attack in player.attacks
        if attack.tournament == tournament
    )

    opponents = orm.select(
        opponent.id
        for opponent in tournament.players
        for group in opponent.groups
        if opponent != player and group in player.groups and opponent not in player_attacks
    )[:]

    if not opponents:
        abort(403, 'No opponents')

    opponent = random.choice(list(opponents))
    return {'id': str(opponent)}


def attack(id):
    validator = Validator({
        'from_player_id': {
            'is_uuid': True,
            'type': 'string',
            'empty': False,
            'required': True
        },
        'to_player_id': {
            'is_uuid': True,
            'type': 'string',
            'empty': False,
            'required': True
        },
    })
    is_valid = validator.validate(request.json)
    if not is_valid:
        abort(400, validator.errors)

    from_player_id = validator.document['from_player_id']
    to_player_id = validator.document['to_player_id']

    if from_player_id == to_player_id:
        abort(400, 'The player cannot attack himself')

    try:
        with orm.db_session:
            tournament = get_object_or_404(Tournament, id=id)
            if tournament.finished:
                abort(403, 'The tournament has ended')
            if not tournament.started:
                abort(403, 'The tournament has not started yet')

            from_player = get_object_or_404(Player, id=from_player_id)
            to_player = get_object_or_404(Player, id=to_player_id)

            frozen = r.get(f'tournament:{tournament.id}:player:{from_player_id}')
            if frozen:
                abort(429, 'Too many attacks')

            attack, created = Attack.get_or_create(
                tournament=tournament,
                from_player=from_player,
                to_player=to_player
            )

            if not created:
                abort(400, 'Player cannot attack twice the same player')

            score = random.randint(-10, 10)
            from_player.medals += score
            to_player.medals -= score
            r.set(f'tournament:{tournament.id}:player:{from_player_id}', 'frozen', ex=5)
    except orm.core.OptimisticCheckError:
        abort(403, 'Attacked by someone else')

    response.status = 201
    return {}


def create_app():

    def uuid_filter(config):
        # @see: https://gist.github.com/alexdeloy/8512024
        regexp = r'[a-f0-9]{8}-?[a-f0-9]{4}-?4[a-f0-9]{3}-?[89ab][a-f0-9]{3}-?[a-f0-9]{12}'

        def to_python(match):
            return match

        def to_url(uuid):
            return uuid

        return regexp, to_python, to_url

    def error_handler(error):
        message = error.body
        # A little bit ugly, but we can use abort() with dicts
        try:
            message = json.loads(message)
        except json.decoder.JSONDecodeError:
            pass
        error.set_header('Content-Type', 'application/json')
        return json.dumps({'error': {'status': error.status_code, 'message': message}})

    app = Bottle()
    app.router.add_filter('uuid', uuid_filter)
    app.config.load_dict({
        'TOURNAMENT_GROUP_SIZE': 50,
        'TOURNAMENT_MAX_PLAYERS': 200,
    })

    app.error(code=400, callback=error_handler)
    app.error(code=403, callback=error_handler)
    app.error(code=404, callback=error_handler)

    routes = [
        Route(app, rule='/admin/player', method='POST', callback=create_player),
        Route(app, rule='/admin/player/<id:uuid>', method='GET', callback=player_detail),
        Route(app, rule='/admin/tournament', method='POST', callback=create_tournament),
        Route(app, rule='/admin/tournament/<id:int>', method='GET', callback=tournament_detail),
        Route(app, rule='/admin/tournament/<id:int>/participate', method='POST', callback=participate),
        Route(app, rule='/game/tournament/<id:int>/opponent/<player_id:uuid>', method='GET', callback=get_opponent),
        Route(app, rule='/game/tournament/<id:int>/attack', method='POST', callback=attack),
    ]
    app.merge(routes)

    db.bind(provider='sqlite', filename='database.sqlite', create_db=True)
    db.generate_mapping(create_tables=True)

    return app


app = create_app()
