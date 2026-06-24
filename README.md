# Auto LMS Multiple Choice

Tool desktop Python co giao dien `tkinter` de OCR cau hoi trac nghiem tren man hinh, so sanh voi bo dap an PDF da import, sau do click dap an dung va click Submit/Next neu da cau hinh.

Chi su dung tool nay trong cac bai luyen tap, noi dung ban co quyen tu dong hoa, hoac moi truong duoc phep.

## Chuc nang

- Chon vung man hinh cho cau hoi, dap an A/B/C/D va nut Submit/Next tuy chon.
- Chon them vung countdown va diem X/Y nut trang ke tiep tuy chon.
- Chon them vung popup/thong bao va diem X/Y can click khi popup xuat hien tuy chon.
- Luu toa do vao `config.json`.
- Import bo dap an tu PDF va luu vao `answer_bank.json`.
- Chi dung bo dap an trong PDF, khong goi AI/OpenAI API.
- Neu countdown het gio, tool tu di chuot den diem trang ke tiep va click trai.
- Neu popup xuat hien, tool tu di chuot den diem popup da chon va click trai.
- `Run Once` xu ly mot cau hoi.
- `Auto Run` lap lien tuc, moi vong doi khoang 2 giay.
- `Stop` dung auto an toan.
- Log OCR, dap an PDF chon va trang thai click.

## Cai dat

Can Python 3.10+.

```bash
pip install -r requirements.txt
```

Can cai them Tesseract OCR tren may:

- Windows: tai va cai Tesseract tu https://github.com/UB-Mannheim/tesseract/wiki
- Khi cai, nen chon them goi ngon ngu Vietnamese neu can OCR tieng Viet.
- Neu `pytesseract` khong tim thay Tesseract, them thu muc cai dat vao `PATH`, vi du:

```powershell
$env:PATH += ";C:\Program Files\Tesseract-OCR"
```

## Cau hinh OCR

Neu OCR tieng Viet khong hoat dong, thu cau hinh ngon ngu OCR:

```powershell
$env:TESSERACT_LANG="eng+vie"
```

## Chay tool

```bash
python main.py
```

## Cach dung

1. Mo website co cau hoi trac nghiem.
2. Chay `python main.py`.
3. Bam `Import PDF` va chon file PDF bo dap an.
4. Bam `Set Regions`.
5. Keo chuot lan luot de chon:
   - Vung cau hoi
   - Vung dap an A
   - Vung dap an B
   - Vung dap an C
   - Vung dap an D
   - Vung nut Submit/Next neu co
   - Vung thoi gian dem nguoc neu co
   - Diem X/Y nut trang ke tiep neu co
   - Vung popup/thong bao neu co
   - Diem X/Y can click khi popup xuat hien neu co
6. O cac buoc tuy chon nhu Submit/Next, countdown, trang ke tiep, popup, bam `Enter` neu muon bo qua.
7. Bam `Run Once` de xu ly 1 cau, hoac `Auto Run` de lap lien tuc.
8. Bam `Stop` de dung auto run.

## Popup/thong bao

Khi cau hinh them vung popup va diem click popup, moi vong chay tool se OCR vung popup truoc. Neu phat hien popup, tool se:

- Di chuyen con tro chuot den diem `popup_click` da cau hinh.
- Click chuot trai.
- Bo qua viec countdown/OCR/chon dap an trong vong hien tai.

Mac dinh, tool coi popup xuat hien khi OCR vung popup co noi dung text. Nen chon vung popup la khu vuc binh thuong trong trang khong co chu, nhung khi popup hien len thi co chu thong bao.

Neu muon giam click nham, co the dat tu khoa popup:

```powershell
$env:POPUP_KEYWORDS="OK,Confirm,Tiếp tục,Dong y"
```

Khi co `POPUP_KEYWORDS`, tool chi click neu OCR popup co mot trong cac tu khoa tren.

Co the thay doi do dai text toi thieu khi khong dung tu khoa:

```powershell
$env:POPUP_MIN_TEXT_LEN="5"
```

## Countdown va nut trang ke tiep

Khi cau hinh them vung countdown, moi vong chay tool se OCR vung nay truoc. Tool co the doc cac dang:

```text
00:00
01:30
1:02:05
0
```

Neu countdown parse duoc va thoi gian con lai <= 0, tool se:

- Di chuyen con tro chuot den diem `next_page` da cau hinh.
- Click chuot trai.
- Bo qua viec OCR/chon dap an trong vong hien tai.

Neu countdown het nhung chua cau hinh diem trang ke tiep, tool se ghi log va khong click.

## Import bo dap an PDF

Nut `Import PDF` doc text trong PDF bang `pypdf`, doc mau chu bang `PyMuPDF`, va co fallback render trang PDF thanh anh de nhan dien hang dap an mau xanh/check. Sau khi parse, tool tao `answer_bank.json`.

Ho tro tot cac PDF dang text co format nhu:

```text
Cau 1: A
Cau 2: B
3. C
Question 4 - Answer: D
```

Hoac cac block co noi dung cau hoi va dong dap an:

```text
Cau 1. Noi dung cau hoi...
A. ...
B. ...
C. ...
D. ...
Dap an: B
```

Hoac PDF co dap an dung nam ngay trong cau hoi, option dung duoc to mau xanh/check:

```text
Cau 1/
1. Phan mat duong va le duong.
2. Phan duong xe chay.  <- option nay mau xanh
3. Phan duong xe co gioi.
```

Voi dang nay tool se doc option mau xanh `1/2/3/4` va doi thanh `A/B/C/D`:

- `1` -> `A`
- `2` -> `B`
- `3` -> `C`
- `4` -> `D`

Neu PDF chi co text `Cau 1/`, con cau hoi/dap an la anh, tool se render tung trang va nhan dien:

- Cac duong ke ngang cua hang dap an.
- Hang nao co mau xanh/check.
- Thu tu hang xanh la option `1/2/3/4`.

Voi file PDF lon 600 cau, import co the mat khoang 30-40 giay.

Khi chay, tool se:

- Uu tien match theo so cau neu OCR doc duoc "Cau 1", "Question 1", "1.".
- Neu PDF co noi dung cau hoi, tool match gan dung theo text OCR.
- Neu khong match duoc PDF, tool ghi log loi va khong click dap an.

Luu y: PDF van can doc duoc nhan `Cau 1/`, `Cau 2/` trong lop text. Neu PDF la anh scan hoan toan khong co text so cau, hay OCR PDF thanh text truoc roi import lai.

## File cau hinh

Sau khi chon vung, tool tao `config.json` co dang:

```json
{
  "regions": {
    "question": {"x": 100, "y": 100, "w": 800, "h": 120},
    "A": {"x": 100, "y": 240, "w": 800, "h": 60},
    "B": {"x": 100, "y": 310, "w": 800, "h": 60},
    "C": {"x": 100, "y": 380, "w": 800, "h": 60},
    "D": {"x": 100, "y": 450, "w": 800, "h": 60},
    "submit": {"x": 700, "y": 540, "w": 160, "h": 50},
    "countdown": {"x": 900, "y": 40, "w": 120, "h": 40},
    "popup": {"x": 420, "y": 260, "w": 440, "h": 180}
  },
  "points": {
    "next_page": {"x": 920, "y": 620},
    "popup_click": {"x": 640, "y": 410}
  }
}
```

Sau khi import PDF, tool tao `answer_bank.json` co dang:

```json
{
  "source_pdf": "D:/duong-dan/bo-dap-an.pdf",
  "imported_at": "2026-06-24 10:00:00",
  "entries": [
    {"number": 1, "question": "", "answer": "A"},
    {"number": 2, "question": "Noi dung cau hoi...", "answer": "B"}
  ]
}
```

## Xu ly loi thuong gap

- `Chua cau hinh du vung`: bam `Set Regions` va chon lai cac vung bat buoc.
- `Chua import PDF dap an`: bam `Import PDF` truoc khi Run Once/Auto Run.
- Import PDF khong co text: PDF co the la anh scan, can OCR PDF thanh text truoc.
- Import PDF khong tim thay dap an: chinh lai PDF/text theo format co so cau va dap an ro rang, hoac dam bao option dung duoc to mau xanh trong text PDF.
- Countdown khong hoat dong: chon vung countdown rong hon, dam bao OCR doc duoc dang `00:00` hoac so giay.
- Het gio nhung khong sang trang: chon lai diem X/Y nut trang ke tiep trong `Set Regions`.
- Popup bi click nham: chon vung popup noi binh thuong khong co chu, hoac dat `POPUP_KEYWORDS`.
- Popup khong duoc click: chon vung popup rong hon va dat diem `popup_click` vao nut can bam trong popup.
- OCR rong hoac sai: chon vung rong hon, zoom trang web lon hon, cai them Vietnamese language data cho Tesseract.
- Khong tim thay dap an trong PDF: dam bao vung cau hoi OCR doc duoc so cau, vi du `Cau 190`, hoac PDF co noi dung cau hoi de match gan dung.
