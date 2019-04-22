import aiohttp
import asyncio
import argparse
import datetime
import logging
import random
import tabulate
from faker import Faker
from mypy_extensions import TypedDict
from typing import NewType, Tuple, List, Dict, Optional
from pprint import pprint as pp


Player = TypedDict('Player', {'name': str, 'power': int, 'medals': int, 'money': int})
PlayerId = NewType('PlayerId', str)
GroupId = NewType('GroupId', str)
TournamentId = NewType('TournamentId', int)

BASE_URL = 'http://localhost:8080'
PLAYER_URL = f'{BASE_URL}/admin/player'
TOURNAMENT_URL = f'{BASE_URL}/admin/tournament'
GAME_URL = f'{BASE_URL}/game/tournament'

parser = argparse.ArgumentParser(description='Simulation of the tournament process.')
parser.add_argument('--players', type=int, default=200, help='Number of players')
parser.add_argument('--verbose', action='store_true', help='Detailed output')

logging.basicConfig(format='%(asctime)s %(message)s', datefmt='[%H:%M:%S]')
log = logging.getLogger()
log.setLevel(logging.INFO)

fake = Faker()


def generate_player() -> Player:
    return {
        'name': fake.name(),
        'power': random.randint(1, 1000),
        'medals': 1000,
        'money': 0
    }


async def create_player(session) -> PlayerId:
    player = generate_player()
    async with session.post(PLAYER_URL, json=player) as response:
        status = response.status
        assert status == 201
        doc = await response.json()
        return doc['id']


async def create_players(n, session) -> List[PlayerId]:
    tasks = [create_player(session) for _ in range(n)]
    return await asyncio.gather(*tasks, return_exceptions=True)


async def create_tournament(start_dt, end_dt, session) -> TournamentId:
    start_timestamp = datetime.datetime.strftime(start_dt, "%Y-%m-%dT%H:%M:%S")
    end_timestamp = datetime.datetime.strftime(end_dt, "%Y-%m-%dT%H:%M:%S")
    payload = {
        'start_timestamp': start_timestamp,
        'end_timestamp': end_timestamp,
    }
    async with session.post(TOURNAMENT_URL, json=payload) as response:
        status = response.status
        assert status == 201
        doc = await response.json()
        return doc['id']


async def participate(tournament_id: TournamentId, player_id: PlayerId, session) -> None:
    participation_url = f'{TOURNAMENT_URL}/{tournament_id}/participate'
    async with session.post(participation_url, json={'player_id': player_id}) as response:
        status = response.status
        assert status == 201


async def enroll_players(tournament_id: TournamentId, players: List[PlayerId], session) -> None:
    tasks = [participate(tournament_id, player, session) for player in players]
    await asyncio.gather(*tasks, return_exceptions=True)


async def tournament_groups(tournament_id: TournamentId, session) -> Dict[GroupId, List[Player]]:
    async with session.get(f'{TOURNAMENT_URL}/{tournament_id}') as response:
        status = response.status
        assert status == 200
        return await response.json()


async def get_opponent(tournament_id: TournamentId, player_id: PlayerId, session) -> Optional[PlayerId]:
    async with session.get(f'{GAME_URL}/{tournament_id}/opponent/{player_id}') as response:
        status = response.status
        assert status in (200, 403)
        if status == 403:
            return None
        doc = await response.json()
        return doc['id']


async def attack(tournament_id: TournamentId, from_player_id: PlayerId, to_player_id: PlayerId, session) -> Tuple[bool, int]:
    payload = {
        'from_player_id': from_player_id,
        'to_player_id': to_player_id,
    }
    async with session.post(f'{GAME_URL}/{tournament_id}/attack', json=payload) as response:
        status = response.status
        assert status in (201, 400, 403, 429)
        return status == 201, status


async def player_attacks(tournament_id: TournamentId, player_id: PlayerId, session) -> None:
    while True:
        opponent_id = await get_opponent(tournament_id, player_id, session)
        if not opponent_id:
            break

        # TODO: Add more useful codes to the server
        success, code = await attack(tournament_id, player_id, opponent_id, session)
        if success:
            await asyncio.sleep(5)
        else:
            if code == 403:
                break
            if code == 429:
                await asyncio.sleep(5)


async def start_attacks(tournament_id: TournamentId, players: List[Player], session) -> None:
    tasks = [player_attacks(tournament_id, player['id'], session) for player in players]
    await asyncio.gather(*tasks)


def print_winners(groups: Dict[GroupId, List[Player]]) -> None:
    for group_id in groups:
        winners = groups[group_id][:3]
        headers = winners[0].keys()
        rows = [winner.values() for winner in winners]
        print(f'\n==== Group:{group_id}:winners ====')
        print(tabulate.tabulate(rows, headers))


async def main(n: int) -> None:
    async with aiohttp.ClientSession() as session: 
        log.info('Create players')
        players = await create_players(n, session=session)

        now = datetime.datetime.now()
        start_dt = now + datetime.timedelta(seconds=5)
        end_dt = now + datetime.timedelta(seconds=125)
        log.info(f'Create tournament ({start_dt}; {end_dt})')
        tournament_id = await create_tournament(start_dt, end_dt, session)

        log.info('Enroll players')
        await enroll_players(tournament_id, players, session)

        delay = start_dt - datetime.datetime.now()
        await asyncio.sleep(delay.seconds)
        log.info('Getting groups')
        groups = {}
        while not groups:
            groups = await tournament_groups(tournament_id, session)

        log.info('Start attacks')
        tasks = [
            start_attacks(tournament_id, players, session)
            for players in groups.values()
        ]
        await asyncio.gather(*tasks)

        delay = end_dt - datetime.datetime.now()
        delay = 5 if delay.days < 0 else delay.seconds
        await asyncio.sleep(delay)
        groups = await tournament_groups(tournament_id, session)
        print_winners(groups)


if __name__ == '__main__':
    args = parser.parse_args()
    if args.verbose:
        log.setLevel(logging.DEBUG)

    loop = asyncio.get_event_loop()
    loop.run_until_complete(main(args.players))
    loop.close()
