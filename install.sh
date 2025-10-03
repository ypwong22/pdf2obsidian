# install homebrew on MacOS
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# install miniforge
brew install --cask miniforge

# create conda environment
conda create -n sci python=3.10 -y
conda init

# exit and re-enter terminal
conda activate sci

# install 
pip install mineru
pip install "paddleocr>=2.7"
pip install "paddlepaddle>=2.5.0"
pip install torch doclayout-yolo transformers
pip install ultralytics
pip install ftfy

pip install dill
export TORCH_FORCE_WEIGHTS_ONLY="false"

pip install omegaconf

# test
mineru extract -p tests/samples/hello.pdf -o out.json