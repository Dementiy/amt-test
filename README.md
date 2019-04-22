Запуск сервера:

```
gunicorn -b localhost:8080 -w 4 backend:app &
```

Запуск воркеров:

```
rq worker --url redis://localhost:6379/1
rq worker --url redis://localhost:6379/1
rqscheduler --host localhost --port 6379 --db 1 
```

Запуск клиентской части:

```
$ python tournament.py --players 200

[22:20:14] Create players
[22:20:16] Create tournament (2019-04-22 22:20:21.270483; 2019-04-22 22:22:21.270483)
[22:20:16] Enroll players
[22:20:20] Getting groups
[22:20:26] Start attacks

==== Group:146:winners ====
id                                    name                power    medals    money
------------------------------------  ----------------  -------  --------  -------
ddf22289-d51b-4194-a52a-513e102d388b  Mary Johnson          549      1084      300
69b3c3d1-6779-45a2-9264-e83d3eba17a8  Aaron Moore           725      1079      200
e5df5a74-8e3a-4b57-9be5-1f251e3027be  Frederick Garcia      521      1068      100

==== Group:145:winners ====
id                                    name                 power    medals    money
------------------------------------  -----------------  -------  --------  -------
b0f5a26b-b19b-4668-ab1a-3a17c12f762c  Matthew Haney          894      1084      300
583e0747-83dd-4bf1-b32f-cd43ad2e5e7f  Elizabeth Turner       793      1068      200
703db92b-b222-4e87-b3bf-46fbc8ae1671  Jonathan Espinoza      937      1055      100

==== Group:147:winners ====
id                                    name                power    medals    money
------------------------------------  ----------------  -------  --------  -------
91912365-9e4f-48f9-b644-3467b35df492  John Livingston       463      1088      300
036316cf-de59-4acd-ac0d-7af05c42321d  Frank Murphy          298      1078      200
fe378882-f85a-4a89-aebc-f27904d4d5c5  Brittany Daniels      448      1055      100

==== Group:148:winners ====
id                                    name                 power    medals    money
------------------------------------  -----------------  -------  --------  -------
2976c0e5-2cce-46af-8deb-fb170627a99b  Dr. Trevor Riddle       20      1127      300
09737acd-e2e9-4e98-a2bd-468d8234e721  Bobby Tran              37      1079      200
9a1d516d-80ad-49ce-9541-d19a08f8b996  Troy Hobbs             244      1070      100
```
