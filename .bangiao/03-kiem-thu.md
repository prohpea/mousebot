# 🧪 [TESTER AGENT] BÁO CÁO THỬ NGHIỆM ĐỘ ỔN ĐỊNH VỚI ĐỘ TRỄ 71MS
**Mã hiệu:** `TST-20261109-CVM-SEC-AIM-71MS-STABILIZATION`  
**Vai trò:** Autonomous QA & Test Engineer (Agency Agent Pipeline)  
**Mô hình vận hành:** `Gemini 3.8 Flash` (Strict Test Executor Mode)  
**Tài liệu thẩm định:** `.bangiao/01-ke-hoach.md`, `.bangiao/02-thay-doi.md`, clip thực tế `MedalTVValorant20261109142241146.mp4`  

---

## 1. Dữ Liệu Thực Nghiệm Trước Khi Vá (Trích Xuất Clip Gameplay)

Số liệu đo đạc vị trí tâm súng qua 10 khung hình liên tiếp khi ngắm vào mục tiêu đầu tiên (Khoảng cách $130\text{px}$ đến $200\text{px}$):
- `Frame 19`: $dx = +45.0\text{ px}$, $dy = -16.0\text{ px}$
- `Frame 20`: $dx = +23.0\text{ px}$, $dy = +9.0\text{ px}$
- `Frame 21`: $dx = +6.0\text{ px}$, $dy = +6.0\text{ px}$
- `Frame 22`: $dx = +35.0\text{ px}$, $dy = +5.0\text{ px}$
- `Frame 24`: $dx = +20.0\text{ px}$, $dy = +23.0\text{ px}$
- `Frame 25`: $dx = +38.0\text{ px}$, $dy = -15.0\text{ px}$

**Nhận định của Tester:**
Tâm súng liên tục bị giật ngược chiều theo trục Y từ $+23\text{px}$ sang $-15\text{px}$ và trục X từ $+6\text{px}$ sang $+38\text{px}$. Đây chính là hiện tượng rung lắc bần bật mà người dùng đã quay video báo lỗi.

---

## 2. Kết Quả Kiểm Thử Sau Khi Vá (71ms Latency Pipeline)

### Test 1: Khả năng triệt tiêu rung giật cận tâm (Deadzone Check)
| Khoảng cách lệch | Lệnh chuột phát ra | Hiện tượng rung lắc | Trạng thái |
| :---: | :---: | :---: | :---: |
| **$0.56\text{ px}$** | $0.0\text{ counts}$ | Hoàn toàn tĩnh lặng ($0\text{Hz}$) | `PASSED` |
| **$1.12\text{ px}$** | $0.0\text{ counts}$ | Hoàn toàn tĩnh lặng ($0\text{Hz}$) | `PASSED` |
| **$1.68\text{ px}$** | $0.0\text{ counts}$ | Hoàn toàn tĩnh lặng ($0\text{Hz}$) | `PASSED` |
| **$2.20\text{ px}$** | $0.0\text{ counts}$ | Hoàn toàn tĩnh lặng ($0\text{Hz}$) | `PASSED` |

### Test 2: Thử nghiệm hội tụ trong môi trường trễ 71ms (14 frames @ 200 FPS)
| Khoảng cách lệch ban đầu ($dx$) | Số lần vọt lố (Overshoots) | Số chu kỳ rung giật | Sai số điểm dừng cuối ($dx_{\text{final}}$) | Thời gian khóa đầu | Trạng thái |
| :---: | :---: | :---: | :---: | :---: | :---: |
| **$6.0\text{ px}$** | **0** | **0 (Không rung)** | **$0.25\text{ px}$** | $165\text{ ms}$ | `PASSED` |
| **$12.0\text{ px}$** | **0** | **0 (Không rung)** | **$-0.08\text{ px}$** | $210\text{ ms}$ | `PASSED` |
| **$18.0\text{ px}$** | **0** | **0 (Không rung)** | **$-0.08\text{ px}$** | $290\text{ ms}$ | `PASSED` |
| **$24.0\text{ px}$** | **0** | **0 (Không rung)** | **$-0.14\text{ px}$** | $375\text{ ms}$ | `PASSED` |

---

## 3. Kết Luận
1. **Dứt điểm rung giật:** Khi tâm chạm vào vùng đầu ($< 2.2\text{px}$), xung chuột được ngắt hoàn toàn, loại bỏ hoàn toàn rung giật tần số cao.
2. **Khóa mục tiêu đầm chắc:** Quá trình lia tâm diễn ra êm mượt, không hề có hiện tượng vọt qua đầu rồi giật lùi lại.
