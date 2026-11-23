# Docker-latex
## About
ローカルでLatexをコンパイルするための構成を含むテンプレートリポジトリです．

## テンプレ集
卒論用のテンプレはここのリポジトリにあります．差し替えて使ってください．
https://github.com/Takahashi-Lab-Keio/latex-template


## Overleafで使う
### 環境構築
- [overleaf](https://www.overleaf.com/)の会員登録
  - 無料枠だと制限があります

### 使い方
1. 左上のCode/Download Zipからzipファイルをダウンロードする
<img width="650" height="556" alt="image" src="https://github.com/user-attachments/assets/aad50b79-423e-48cb-90c8-1af85d330897" />

2. New Project/Upload Projectからダウンロードしたzipファイルをアップロードする
<img width="379" height="369" alt="image" src="https://github.com/user-attachments/assets/81002774-c01e-4827-9f4f-50f36b1d1083" />

3. File/Settings/CompilerからコンパイラをLaTeXに変更する
<img width="423" height="638" alt="image" src="https://github.com/user-attachments/assets/f67b0af9-c434-4b09-96d3-36be193ce1bf" />
<img width="1070" height="224" alt="image" src="https://github.com/user-attachments/assets/2379cde0-d8a1-4e24-992f-a016148501c1" />

## Github Codespacesで使う
### 環境構築
- Github アカウント
    - 無料枠だと制限があります

### 使い方
1. Use this template / Create a new repository から新しい自分用のリポジトリを作る．
<img width="529" height="294" alt="image" src="https://github.com/user-attachments/assets/5c0058b9-2372-4b14-8259-ddf864293f2e" />

2. 作った自分のリポジトリでCode/Codespaces/Create Codespaces on main を押す．
<img width="635" height="578" alt="image" src="https://github.com/user-attachments/assets/a63f97bd-9bba-4140-adbe-64dfe2d43424" />


## ローカル（docker環境）で使う
### 環境構築
- Docker
  - Windows/Macは[こちら](https://www.docker.com/ja-jp/products/docker-desktop/)
  - Linux(Ubuntu)は[こちら](https://docs.docker.com/engine/install/ubuntu/)
- VSCode
  - Dev Containers拡張機能

### 使い方
1. Use this template / Create a new repository から新しい自分用のリポジトリを作る．
<img width="529" height="294" alt="image" src="https://github.com/user-attachments/assets/5c0058b9-2372-4b14-8259-ddf864293f2e" />

2. 作ったリポジトリをcloneする．

3. VSCodeで開く．拡張機能からDev Containersを探して入れてください．
<img width="1556" height="351" alt="image" src="https://github.com/user-attachments/assets/320f60b2-13ad-4750-bd7a-990144dc864e" />

4. F1キーを押し，コマンドパレットから`Reopen in container` を探して実行してください．または右下の通知から「再度開く」を選択してください．
<img width="1222" height="244" alt="image" src="https://github.com/user-attachments/assets/8f31d510-85da-47e5-819e-8c7e4bafa1fa" />

<img width="946" height="327" alt="image" src="https://github.com/user-attachments/assets/d23f0e5b-2a7a-4251-a17b-a5f9d86375d9" />

