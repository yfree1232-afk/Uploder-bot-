# Use a Python 3.12.3 Alpine base image
FROM python:3.12-alpine3.20

# Set the working directory
WORKDIR /app

# Copy all files from the current directory to the container's /app directory
COPY . .

# Install necessary dependencies
RUN apk add --no-cache \
    gcc \
    libffi-dev \
    musl-dev \
    ffmpeg \
    aria2 \
    make \
    g++ \
    cmake \
    bash \
    curl \
    unzip && \
    curl -L https://www.bento4.com/downloads/Bento4-SDK-1-6-0-639.x86_64-unknown-linux.zip -o bento4.zip && \
    unzip bento4.zip && \
    mv Bento4-SDK-1-6-0-639.x86_64-unknown-linux/bin/mp4decrypt /usr/local/bin/ && \
    chmod +x /usr/local/bin/mp4decrypt && \
    rm -rf bento4.zip Bento4-SDK*

    
# Install Python dependencies
RUN pip3 install --no-cache-dir --upgrade pip \
    && pip3 install --no-cache-dir --upgrade -r sainibots.txt \
    && python3 -m pip install -U yt-dlp

# Set the command to run the application
CMD ["sh", "-c", "python3 main.py"]

