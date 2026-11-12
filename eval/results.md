# HabitatVLM results

Episodes: 16  ·  tasks: 8  ·  filter: since 2026-11-12T10:10:30

## Summary by backend

| Backend | Model | Episodes | Success | Easy | Medium | Hard | Avg steps (successes) | Avg model latency / step | Invalid replies |
|---|---|---|---|---|---|---|---|---|---|
| kaggle · prompt v2 | qwen3-vl:8b-instruct | 8 | **6/8 (75%)** | – | – | 6/8 (75%) | 9.8 | 4.7 s | 0% (0/88) |
| kaggle · prompt v3 | qwen3-vl:8b-instruct | 8 | **5/8 (62%)** | – | – | 5/8 (62%) | 10.2 | 5.0 s | 0% (0/95) |

## Per task

| Task | Tier | Instruction | kaggle · prompt v2 | kaggle · prompt v3 |
|---|---|---|---|---|
| T07 | hard | Put the green canister in the right cabinet and close it | ✅ 1/1 · 8 steps | ✅ 1/1 · 7 steps |
| T08 | hard | Put the red and blue canisters in the right cabinet | ❌ 0/1 · 14 steps | ❌ 0/1 · 14 steps |
| T19 | hard | Put the red canister in the left cabinet and the blue canister in the right cabinet | ✅ 1/1 · 11 steps | ✅ 1/1 · 11 steps |
| T20 | hard | Put the toolbox in the left cabinet and close it | ✅ 1/1 · 7 steps | ✅ 1/1 · 7 steps |
| T21 | hard | Move both canisters from the shelf to the table | ❌ 0/1 · 15 steps | ✅ 1/1 · 15 steps |
| T22 | hard | Put the toolbox in the right cabinet and the green canister on the shelf | ✅ 1/1 · 10 steps | ❌ 0/1 · 15 steps |
| T23 | hard | Put the red, blue and green canisters in the left cabinet | ✅ 1/1 · 14 steps | ❌ 0/1 · 15 steps |
| T24 | hard | Put the red canister in the left cabinet and make sure both cabinets are closed | ✅ 1/1 · 9 steps | ✅ 1/1 · 11 steps |

## Failure analysis

**kaggle · prompt v2** — 2 failed episodes
- said done too early / wrong result: 1
- step limit: repeated failing actions: 1
- failed robot actions (all episodes): container closed ×3, out of reach ×3, gripper full/empty ×3

**kaggle · prompt v3** — 3 failed episodes
- step limit: repeated failing actions: 2
- said done too early / wrong result: 1
- failed robot actions (all episodes): out of reach ×10, gripper full/empty ×7, container closed ×2

### Failed episodes (for review)

| Backend | Task | Steps | Reason |
|---|---|---|---|
| kaggle · prompt v2 | T08 | 14 | model said done / OK red_canister in cabinet_right (actually at cabinet_right); NO blue_canister in cabinet_right (actually at cabinet_left) |
| kaggle · prompt v2 | T21 | 15 | step limit (15) reached / NO red_canister on table (actually at shelf_a); NO blue_canister on table (actually held by robot) |
| kaggle · prompt v3 | T08 | 14 | model said done / OK red_canister in cabinet_right (actually at cabinet_right); NO blue_canister in cabinet_right (actually held by robot) |
| kaggle · prompt v3 | T22 | 15 | step limit (15) reached / NO toolbox in cabinet_right (actually at table); OK green_canister on shelf_a (actually at shelf_a) |
| kaggle · prompt v3 | T23 | 15 | step limit (15) reached / NO red_canister in cabinet_left (actually held by robot); NO blue_canister in cabinet_left (actually at shelf_a);  |

Charts: `charts/success_by_tier.png`, `charts/steps_by_tier.png`
