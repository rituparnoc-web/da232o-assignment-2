# HabitatVLM results

Episodes: 48  ·  tasks: 24  ·  filter: since 2026-11-12T10:10:30

## Summary by backend

| Backend | Model | Episodes | Success | Easy | Medium | Hard | Avg steps (successes) | Avg model latency / step | Invalid replies |
|---|---|---|---|---|---|---|---|---|---|
| kaggle · prompt v2 | qwen3-vl:8b-instruct | 24 | **22/24 (92%)** | 8/8 (100%) | 8/8 (100%) | 6/8 (75%) | 6.3 | 4.7 s | 0% (0/167) |
| kaggle · prompt v3 | qwen3-vl:8b-instruct | 24 | **20/24 (83%)** | 7/8 (88%) | 8/8 (100%) | 5/8 (62%) | 5.9 | 4.9 s | 0% (0/165) |

## Per task

| Room | Task | Tier | Instruction | kaggle · prompt v2 | kaggle · prompt v3 |
|---|---|---|---|---|---|
| room_01 | T01 | easy | Open the left cabinet | ✅ 1/1 · 3 steps | ✅ 1/1 · 3 steps |
| room_01 | T02 | easy | Open the right cabinet | ✅ 1/1 · 3 steps | ✅ 1/1 · 3 steps |
| room_01 | T03 | easy | Pick up the blue canister | ✅ 1/1 · 3 steps | ✅ 1/1 · 3 steps |
| room_01 | T09 | easy | Pick up the red canister | ✅ 1/1 · 3 steps | ✅ 1/1 · 3 steps |
| room_01 | T10 | easy | Pick up the green canister | ✅ 1/1 · 3 steps | ✅ 1/1 · 3 steps |
| room_01 | T11 | easy | Pick up the toolbox | ✅ 1/1 · 3 steps | ✅ 1/1 · 3 steps |
| room_01 | T12 | easy | Open the purple cabinet | ✅ 1/1 · 3 steps | ❌ 0/1 · 3 steps |
| room_01 | T13 | easy | Pick up the canister that is on the table | ✅ 1/1 · 3 steps | ✅ 1/1 · 3 steps |
| room_01 | T04 | medium | Put the red canister in the left cabinet | ✅ 1/1 · 7 steps | ✅ 1/1 · 6 steps |
| room_01 | T05 | medium | Put the toolbox on the shelf | ✅ 1/1 · 6 steps | ✅ 1/1 · 6 steps |
| room_01 | T06 | medium | Move the green canister from the table to the shelf | ✅ 1/1 · 6 steps | ✅ 1/1 · 6 steps |
| room_01 | T14 | medium | Put the blue canister on the table | ✅ 1/1 · 6 steps | ✅ 1/1 · 6 steps |
| room_01 | T15 | medium | Put the blue canister in the right cabinet | ✅ 1/1 · 6 steps | ✅ 1/1 · 6 steps |
| room_01 | T16 | medium | Put the toolbox in the orange cabinet | ✅ 1/1 · 13 steps | ✅ 1/1 · 6 steps |
| room_01 | T17 | medium | Open both cabinets | ✅ 1/1 · 5 steps | ✅ 1/1 · 4 steps |
| room_01 | T18 | medium | Put the red canister on the table | ✅ 1/1 · 6 steps | ✅ 1/1 · 6 steps |
| room_01 | T07 | hard | Put the green canister in the right cabinet and close it | ✅ 1/1 · 8 steps | ✅ 1/1 · 7 steps |
| room_01 | T08 | hard | Put the red and blue canisters in the right cabinet | ❌ 0/1 · 14 steps | ❌ 0/1 · 14 steps |
| room_01 | T19 | hard | Put the red canister in the left cabinet and the blue canister in the right cabinet | ✅ 1/1 · 11 steps | ✅ 1/1 · 11 steps |
| room_01 | T20 | hard | Put the toolbox in the left cabinet and close it | ✅ 1/1 · 7 steps | ✅ 1/1 · 7 steps |
| room_01 | T21 | hard | Move both canisters from the shelf to the table | ❌ 0/1 · 15 steps | ✅ 1/1 · 15 steps |
| room_01 | T22 | hard | Put the toolbox in the right cabinet and the green canister on the shelf | ✅ 1/1 · 10 steps | ❌ 0/1 · 15 steps |
| room_01 | T23 | hard | Put the red, blue and green canisters in the left cabinet | ✅ 1/1 · 14 steps | ❌ 0/1 · 15 steps |
| room_01 | T24 | hard | Put the red canister in the left cabinet and make sure both cabinets are closed | ✅ 1/1 · 9 steps | ✅ 1/1 · 11 steps |

## Failure analysis

**kaggle · prompt v2** — 2 failed episodes
- said done too early / wrong result: 1
- step limit: repeated failing actions: 1
- failed robot actions (all episodes): out of reach ×7, container closed ×3, gripper full/empty ×3

**kaggle · prompt v3** — 4 failed episodes
- said done too early / wrong result: 2
- step limit: repeated failing actions: 2
- failed robot actions (all episodes): out of reach ×13, gripper full/empty ×7, container closed ×2

### Failed episodes (for review)

| Backend | Task | Steps | Reason |
|---|---|---|---|
| kaggle · prompt v2 | T08 | 14 | model said done / OK red_canister in cabinet_right (actually at cabinet_right); NO blue_canister in cabinet_right (actually at cabinet_left) |
| kaggle · prompt v2 | T21 | 15 | step limit (15) reached / NO red_canister on table (actually at shelf_a); NO blue_canister on table (actually held by robot) |
| kaggle · prompt v3 | T08 | 14 | model said done / OK red_canister in cabinet_right (actually at cabinet_right); NO blue_canister in cabinet_right (actually held by robot) |
| kaggle · prompt v3 | T12 | 3 | model said done / cabinet_left open (actually closed) |
| kaggle · prompt v3 | T22 | 15 | step limit (15) reached / NO toolbox in cabinet_right (actually at table); OK green_canister on shelf_a (actually at shelf_a) |
| kaggle · prompt v3 | T23 | 15 | step limit (15) reached / NO red_canister in cabinet_left (actually held by robot); NO blue_canister in cabinet_left (actually at shelf_a);  |

Charts: `charts/success_by_tier.png`, `charts/steps_by_tier.png`
