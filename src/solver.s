# RV32I 2x2x2 cube solver for Ripes (text output + LED Matrix animation).
#
# Build the Ripes file:  python scripts/build_ripes.py   -> build/rubik_ripes.s
# Change the input: edit the "tests" table below (14 digits per state), or run
#      `python scripts/build_ripes.py <state>` for a single-state build.
# Self-check: every answer is replayed on the cubie arrays and must end solved
#      (and match the expected length when one is given). The exit code is the
#      number of failed test cases, so 0 means everything passed.
# LED: Ripes I/O tab -> add "LED Matrix" (it must be named LED Matrix 0),
#      Width 35, Height 25. The net shows U / L F R B / D.
#      Frames: scramble, then one frame after each move, ending solved.
#      Slow down / speed up the animation with "delay_count" below.
# Renderer switch: this Ripes build has no .if directive, so the lines between
#      RENDER_BEGIN / RENDER_END markers are dropped by
#      `python scripts/build_ripes.py --no-render` (CLI build for --iret).
#      The two builds differ only in those marked lines.
#
# Rules kept: RV32I only (no mul/div), no heap, no recursion, no floats,
# no full distance table. Only quarter-turn move tables are precomputed;
# the two small pruning tables are built at startup by BFS.
#
# Algorithm: IDA* with an explicit stack. The search starts from the inverse
# of the input and tries moves in the original BFS order (R, B, D; 1..3
# quarter turns), so the first solution is the lexicographically smallest
# shortest path. Printing it reversed and inverted gives exactly the output
# of sysprog21/minirubik.

.data
# ---- every block below keeps a size that is a multiple of 4 ----
# Test cases, 20 bytes each: expected length (255 = do not check), then the
# 14-digit state as a string, then padding.
# TESTS_BEGIN
tests:
    .byte 0
    .string "12345671111111"            # solved cube
    .zero 4
    .byte 3
    .string "23745612123332"            # short scramble (R B D)
    .zero 4
    .byte 11
    .string "21345671111111"            # distance 11 (assignment vector)
    .zero 4
# TESTS_END
tests_end:
test_ptr:   .word 0                     # address of the current test case
fail_count: .word 0                     # becomes the exit code
fail_msg:   .string "FAIL"              # 5 bytes
            .zero 3                     # pad to 8
face_chr:   .string "RBD"               # 4 bytes
fact:       .half 720, 120, 24, 6, 2, 1, 0, 0   # (6 - i)! for the Lehmer rank
err_msg:    .string "invalid"           # 8 bytes
# RENDER_BEGIN
delay_count: .word 100000               # busy-wait loops between LED frames
# RENDER_END
st_perm:    .zero 8                     # input permutation (0..6)
st_twist:   .zero 8                     # input twists (0..2)
inv_perm:   .zero 8                     # inverse state
inv_twist:  .zero 8
tmp_perm:   .zero 8                     # scratch for apply_quarter
tmp_twist:  .zero 8
path:       .zero 12                    # move per depth: face << 2 | (turns - 1)
frames:     .zero 432                   # 12 DFS frames x 36 bytes
queue:      .zero 10080                 # BFS queue, 5040 halfwords
perm_prune: .zero 5040                  # lower bound from permutation only
twist_prune: .zero 732                  # lower bound from twists only (729 + pad)
# Move tables (perm_mv_R/B/D, twist_mv_R/B/D) are appended from src/tables.s.

# DFS frame layout (36 bytes)
#   0 perm      4 twist     8 last_face  12 face     16 turns
#  20 cur_perm 24 cur_twist 28 perm_tbl  32 twist_tbl

.text
main:
    # ================= pruning tables (runtime BFS, built once) =================
    la   a0, perm_mv_R
    li   a1, 10080              # bytes per face in perm tables
    la   a2, perm_prune
    li   a3, 5040
    jal  ra, build_prune
    la   a0, twist_mv_R
    li   a1, 1460               # bytes per face in twist tables (730 halfwords)
    la   a2, twist_prune
    li   a3, 729
    jal  ra, build_prune

    la   t0, tests
    la   t1, test_ptr
    sw   t0, 0(t1)

    # ================= next test case: parse and validate =================
test_loop:
    la   t1, test_ptr
    lw   t0, 0(t1)
    la   t2, tests_end
    bgeu t0, t2, all_done
    addi t0, t0, 1              # skip the expected-length byte
    la   t1, st_perm
    la   t2, st_twist
    li   t3, 0                  # i
    li   t4, 0                  # bitmask of seen cubies
    li   t5, 0                  # twist sum
    li   t6, 7
parse_loop:
    lbu  a0, 0(t0)              # permutation digit
    addi a0, a0, -49            # '1' -> 0
    bgeu a0, t6, invalid        # also catches non-digits and short input
    li   a1, 1
    sll  a1, a1, a0
    and  a2, t4, a1
    bnez a2, invalid            # duplicate cubie
    or   t4, t4, a1
    sb   a0, 0(t1)
    lbu  a0, 7(t0)              # twist digit
    addi a0, a0, -49
    li   a1, 3
    bgeu a0, a1, invalid
    sb   a0, 0(t2)
    add  t5, t5, a0
    addi t0, t0, 1
    addi t1, t1, 1
    addi t2, t2, 1
    addi t3, t3, 1
    blt  t3, t6, parse_loop
    lbu  a0, 7(t0)              # must end right after 14 digits
    bnez a0, invalid
mod3_loop:                      # twist sum mod 3 by repeated subtraction
    blt  t5, a1, mod3_done
    sub  t5, t5, a1
    j    mod3_loop
mod3_done:
    bnez t5, invalid

# RENDER_BEGIN
    jal  ra, draw_frame         # LED frame 0: the scramble
    li   t6, 7                  # restore constants clobbered by draw_frame
    li   a1, 3
# RENDER_END

    # ================= inverse state =================
    # inv_perm[perm[i]] = i
    la   t0, st_perm
    la   t1, inv_perm
    li   t3, 0
inv_p_loop:
    add  a0, t0, t3
    lbu  a0, 0(a0)
    add  a0, t1, a0
    sb   t3, 0(a0)
    addi t3, t3, 1
    blt  t3, t6, inv_p_loop
    # inv_twist[i] = (3 - twist[inv_perm[i]]) mod 3
    la   t2, st_twist
    la   t4, inv_twist
    li   t3, 0
inv_t_loop:
    add  a0, t1, t3
    lbu  a0, 0(a0)
    add  a0, t2, a0
    lbu  a0, 0(a0)
    beqz a0, inv_t_store
    sub  a0, a1, a0             # a1 = 3
inv_t_store:
    add  a2, t4, t3
    sb   a0, 0(a2)
    addi t3, t3, 1
    blt  t3, t6, inv_t_loop

    # ================= rank the inverse state =================
    # s3 = Lehmer rank of inv_perm, with no multiplication: for every
    # element to the right of position i that is smaller than p[i], add
    # (6 - i)! once. The seven factorials come from the "fact" table.
    li   s3, 0
    li   t3, 0                  # i
    la   a4, fact
rank_i_loop:
    add  a0, t1, t3
    lbu  a0, 0(a0)              # p[i]
    lhu  a2, 0(a4)              # (6 - i)!
    addi t5, t3, 1              # j = i + 1
rank_j_loop:
    bge  t5, t6, rank_j_done
    add  a3, t1, t5
    lbu  a3, 0(a3)
    bgeu a3, a0, rank_j_next
    add  s3, s3, a2             # p[j] < p[i]
rank_j_next:
    addi t5, t5, 1
    j    rank_j_loop
rank_j_done:
    addi a4, a4, 2
    addi t3, t3, 1
    blt  t3, t6, rank_i_loop
    # s4 = base-3 rank of the first six twists
    li   s4, 0
    li   t3, 0
    li   a1, 6
rank_t_loop:
    add  a0, t4, t3
    lbu  a0, 0(a0)
    slli a2, s4, 1
    add  s4, a2, s4             # s4 * 3
    add  s4, s4, a0
    addi t3, t3, 1
    blt  t3, a1, rank_t_loop

    # ================= IDA* setup =================
    la   s10, perm_prune
    la   s11, twist_prune
    la   a2, perm_mv_R          # face-0 table bases, reset for every new frame
    la   a3, twist_mv_R
    la   a6, path
    la   a7, frames
    sw   s3, 0(a7)              # frame 0 = root (inverse state)
    sw   s4, 4(a7)
    li   s0, 0                  # depth / solution length
    add  t0, s10, s3
    lbu  s1, 0(t0)
    add  t0, s11, s4
    lbu  t0, 0(t0)
    bgeu s1, t0, root_h_done
    mv   s1, t0
root_h_done:                    # s1 = bound = h(root)
    beqz s1, found              # already solved
    li   t6, 3
    li   t5, 10080
    li   t4, 1460

new_bound:                      # (re)start DFS from the root
    mv   s2, a7
    li   s0, 0
    lw   s3, 0(s2)
    lw   s4, 4(s2)
    li   s7, -1                 # root has no last face
    li   s5, 0                  # face
    li   s6, 0                  # quarter turns applied so far
    mv   a4, a2                 # perm table of current face
    mv   a5, a3                 # twist table of current face

next_child:
    beq  s6, t6, adv_face       # all 3 turns of this face tried
    bnez s6, apply_turn
    mv   s8, s3                 # first turn starts from the node itself
    mv   s9, s4
apply_turn:                     # one more quarter turn (cumulative)
    slli t0, s8, 1
    add  t0, a4, t0
    lhu  s8, 0(t0)
    slli t0, s9, 1
    add  t0, a5, t0
    lhu  s9, 0(t0)
    addi s6, s6, 1
    add  t0, s10, s8            # h = max(perm_prune, twist_prune)
    lbu  t0, 0(t0)
    add  t1, s11, s9
    lbu  t1, 0(t1)
    bgeu t0, t1, h_done
    mv   t0, t1
h_done:
    add  t1, s0, t0
    addi t1, t1, 1
    blt  s1, t1, next_child     # depth + 1 + h > bound: prune
    slli t1, s5, 2              # record move = face << 2 | (turns - 1)
    add  t1, t1, s6
    addi t1, t1, -1
    add  t2, a6, s0
    sb   t1, 0(t2)
    addi s0, s0, 1
    bnez t0, push
    beq  s0, s1, found          # h == 0 means solved
push:
    sw   s5, 12(s2)             # save loop state of the parent frame
    sw   s6, 16(s2)
    sw   s8, 20(s2)
    sw   s9, 24(s2)
    sw   a4, 28(s2)
    sw   a5, 32(s2)
    addi s2, s2, 36
    mv   s7, s5                 # child: last_face = face just used
    mv   s3, s8
    mv   s4, s9
    sw   s3, 0(s2)
    sw   s4, 4(s2)
    sw   s7, 8(s2)
    li   s5, 0
    li   s6, 0
    mv   a4, a2
    mv   a5, a3
    beqz s7, adv_face           # never turn the same face twice in a row
    j    next_child

adv_face:
    addi s5, s5, 1
    li   s6, 0
    add  a4, a4, t5
    add  a5, a5, t4
    beq  s5, s7, adv_face
    blt  s5, t6, next_child
    beqz s0, bound_up           # root exhausted: deepen
    addi s2, s2, -36            # pop: restore parent frame
    addi s0, s0, -1
    lw   s3, 0(s2)
    lw   s4, 4(s2)
    lw   s7, 8(s2)
    lw   s5, 12(s2)
    lw   s6, 16(s2)
    lw   s8, 20(s2)
    lw   s9, 24(s2)
    lw   a4, 28(s2)
    lw   a5, 32(s2)
    j    next_child

bound_up:
    addi s1, s1, 1
    li   t0, 12
    blt  s1, t0, new_bound
    j    invalid                # unreachable for valid cubes (diameter 11)

    # ================= print the solution =================
    # Walk path backwards; each move is inverted: n -> 2 - n.
found:
    la   t2, face_chr
    mv   t3, s0                 # i = length
    li   s9, 0                  # 0 until the first move is printed
    li   a7, 11                 # ecall: print char
print_loop:
    beqz t3, print_end
    addi t3, t3, -1
    beqz s9, print_face
    li   a0, 32                 # ' '
    ecall
print_face:
    li   s9, 1
    add  t0, a6, t3
    lbu  t0, 0(t0)
    srli t1, t0, 2              # face
    andi t0, t0, 3              # turns - 1
    add  t1, t2, t1
    lbu  a0, 0(t1)
    ecall
    li   t1, 1
    beq  t0, t1, print_two      # 2 quarter turns -> "2"
    bnez t0, print_loop         # 3 quarter turns -> inverse is 1 -> ""
    li   a0, 39                 # 1 quarter turn -> inverse is "'"
    ecall
    j    print_loop
print_two:
    li   a0, 50                 # '2'
    ecall
    j    print_loop
print_end:
    li   a0, 10                 # '\n'
    ecall

    # ================= replay and self-check (gate T5) =================
    # Apply the printed moves to the input cubie arrays. With the renderer
    # enabled this is also the animation: one LED frame per move.
    mv   s1, s0                 # i = length
anim_loop:
    beqz s1, anim_end
    addi s1, s1, -1
    add  t0, a6, s1
    lbu  t0, 0(t0)
    srli s2, t0, 2              # face
    andi t0, t0, 3
    li   s3, 3
    sub  s3, s3, t0             # printed move = 3 - n quarter turns
# RENDER_BEGIN
    la   t0, delay_count        # let the previous frame stay visible
    lw   t0, 0(t0)
    beqz t0, anim_turn
delay_loop:
    addi t0, t0, -1
    bnez t0, delay_loop
# RENDER_END
anim_turn:
    mv   a0, s2
    jal  ra, apply_quarter
    addi s3, s3, -1
    bnez s3, anim_turn
# RENDER_BEGIN
    jal  ra, draw_frame
# RENDER_END
    j    anim_loop
anim_end:
    la   t0, st_perm            # the cube must now be solved:
    la   t1, st_twist           # perm[i] == i and twist[i] == 0 for all i
    li   t2, 0
    li   t3, 7
check_loop:
    add  t4, t0, t2
    lbu  t4, 0(t4)
    bne  t4, t2, test_fail
    add  t4, t1, t2
    lbu  t4, 0(t4)
    bnez t4, test_fail
    addi t2, t2, 1
    blt  t2, t3, check_loop
    la   t0, test_ptr           # and the length must match when one is given
    lw   t0, 0(t0)
    lbu  t0, 0(t0)
    li   t1, 255
    beq  t0, t1, test_done
    beq  t0, s0, test_done
test_fail:
    la   a0, fail_msg
    j    report_fail
invalid:
    la   a0, err_msg
report_fail:
    li   a7, 4                  # ecall: print string
    ecall
    li   a0, 10
    li   a7, 11
    ecall
    la   t0, fail_count
    lw   t1, 0(t0)
    addi t1, t1, 1
    sw   t1, 0(t0)
test_done:
    la   t0, test_ptr
    lw   t1, 0(t0)
    addi t1, t1, 20             # next test case
    sw   t1, 0(t0)
    j    test_loop

all_done:
    la   t0, fail_count
    lw   a0, 0(t0)              # exit code = number of failed tests
    li   a7, 93                 # ecall: exit with code
    ecall

# RENDER_BEGIN
# ------------------------------------------------------------------
# draw_frame: paint st_perm/st_twist on the LED matrix (leaf).
#   Sticker (pos, facelet j) shows cubie colour (j - twist) mod 3.
#   Position 0 always holds cubie 0 with twist 0.
#   Uses t0-t6, a0-a5.
# ------------------------------------------------------------------
draw_frame:
    li   t0, LED_MATRIX_0_BASE
    la   t1, led_off            # advances 12 bytes per position
    la   t2, cubie_rgb
    la   t3, st_perm
    la   t4, st_twist
    li   t5, 0                  # position
df_pos:
    li   a0, 0                  # cubie
    li   a1, 0                  # twist
    beqz t5, df_have
    add  a0, t3, t5
    lbu  a0, -1(a0)
    addi a0, a0, 1
    add  a1, t4, t5
    lbu  a1, -1(a1)
df_have:
    slli a2, a0, 3              # a2 = colour row = cubie_rgb + cubie * 12
    slli a0, a0, 2
    add  a2, a2, a0
    add  a2, t2, a2
    li   a0, LED_MATRIX_0_WIDTH # a0 = bytes per LED row = WIDTH * 4
    slli a0, a0, 2
    li   a3, 0                  # facelet j
df_face:
    sub  a4, a3, a1             # h = (j - twist) mod 3
    bgez a4, df_h_ok
    addi a4, a4, 3
df_h_ok:
    slli a4, a4, 2
    add  a4, a2, a4
    lw   a4, 0(a4)              # colour
    slli a5, a3, 2
    add  a5, t1, a5
    lw   a5, 0(a5)              # LED byte offset of the sticker
    add  a5, t0, a5
    li   t6, 3                  # 3 rows of 4 LEDs
df_row:
    sw   a4, 0(a5)
    sw   a4, 4(a5)
    sw   a4, 8(a5)
    sw   a4, 12(a5)
    add  a5, a5, a0             # next LED row
    addi t6, t6, -1
    bnez t6, df_row
    addi a3, a3, 1
    li   t6, 3
    blt  a3, t6, df_face
    addi t1, t1, 12
    addi t5, t5, 1
    li   t6, 8
    blt  t5, t6, df_pos
df_done:                        # frame complete
    ret

# RENDER_END
# ------------------------------------------------------------------
# apply_quarter: one clockwise quarter turn of face a0 (0=R 1=B 2=D)
#   on st_perm/st_twist, using turn_src/turn_add (leaf). Uses t0-t6, a1-a5.
# ------------------------------------------------------------------
apply_quarter:
    slli t0, a0, 3              # face * 7 = face * 8 - face
    sub  t0, t0, a0
    la   t1, turn_src
    add  t1, t1, t0
    la   t2, turn_add
    add  t2, t2, t0
    la   t3, st_perm
    la   t4, st_twist
    la   a1, tmp_perm
    la   a2, tmp_twist
    li   t5, 0                  # i
    li   t6, 7
aq_loop:
    add  a3, t1, t5
    lbu  a3, 0(a3)              # source index
    add  a4, t3, a3
    lbu  a4, 0(a4)
    add  a5, a1, t5
    sb   a4, 0(a5)              # tmp_perm[i] = perm[src]
    add  a4, t4, a3
    lbu  a4, 0(a4)
    add  a5, t2, t5
    lbu  a5, 0(a5)
    add  a4, a4, a5             # twist[src] + add[i], then mod 3
    li   a5, 3
    blt  a4, a5, aq_mod_ok
    addi a4, a4, -3
aq_mod_ok:
    add  a5, a2, t5
    sb   a4, 0(a5)
    addi t5, t5, 1
    blt  t5, t6, aq_loop
    li   t5, 0                  # copy tmp back
aq_copy:
    add  a3, a1, t5
    lbu  a4, 0(a3)
    add  a3, t3, t5
    sb   a4, 0(a3)
    add  a3, a2, t5
    lbu  a4, 0(a3)
    add  a3, t4, t5
    sb   a4, 0(a3)
    addi t5, t5, 1
    blt  t5, t6, aq_copy
    ret

# ------------------------------------------------------------------
# build_prune: BFS from solved over one coordinate (leaf, no stack).
#   a0 = move table base (face 0), a1 = bytes per face,
#   a2 = prune table,             a3 = number of states
# ------------------------------------------------------------------
build_prune:
    li   t0, 0xFF               # unseen marker
    mv   t1, a2
    add  t2, a2, a3
bp_fill:
    sb   t0, 0(t1)
    addi t1, t1, 1
    bltu t1, t2, bp_fill
    sb   zero, 0(a2)            # solved state has distance 0
    la   t1, queue              # t1 = head pointer
    sh   zero, 0(t1)
    addi t2, t1, 2              # t2 = tail pointer
bp_loop:
    bgeu t1, t2, bp_done
    lhu  t3, 0(t1)              # current state
    addi t1, t1, 2
    add  a4, a2, t3
    lbu  a4, 0(a4)
    addi a4, a4, 1              # distance of neighbours
    mv   a5, a0                 # table of current face
    li   a6, 3                  # faces left
bp_face:
    mv   t4, t3
    li   a7, 3                  # quarter turns left
bp_turn:
    slli t5, t4, 1
    add  t5, a5, t5
    lhu  t4, 0(t5)
    add  t5, a2, t4
    lbu  t6, 0(t5)
    bne  t6, t0, bp_seen
    sb   a4, 0(t5)
    sh   t4, 0(t2)
    addi t2, t2, 2
bp_seen:
    addi a7, a7, -1
    bnez a7, bp_turn
    add  a5, a5, a1
    addi a6, a6, -1
    bnez a6, bp_face
    j    bp_loop
bp_done:
    ret
