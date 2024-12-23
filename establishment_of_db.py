import cv2  # For video and image processing
import os  # For file and directory operations
import numpy as np  # For numerical operations
import pywt  # For computing Discrete Wavelet Transform (DWT)
import librosa  # For audio processing and feature extraction
import time # For timing the process
import sqlite3  # For SQLite database operations
import json  # For saving and loading progress
import signal  # For handling keyboard interrupts

# Progress file path
PROGRESS_FILE = "progress.json"

# Utility functions
def save_progress(progress):
    with open(PROGRESS_FILE, 'w') as f:
        json.dump(progress, f)

def load_progress():
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE, 'r') as f:
            return json.load(f)
    return None

def reset_progress():
    if os.path.exists(PROGRESS_FILE):
        os.remove(PROGRESS_FILE)

def extract_frames(video_path, output_dir):
    # Open the video file
    cap = cv2.VideoCapture(video_path)
    frames = [] # List to store the paths of extracted frames
    # Get the name of the video file without extension
    video_name = os.path.splitext(os.path.basename(video_path))[0]
    # Create a directory to save the extracted frames
    frame_dir = os.path.join(output_dir, f"frames_{video_name}")
    os.makedirs(frame_dir, exist_ok=True)

    count = 0  # Frame counter
    # Loop through the video frames
    while cap.isOpened():
        ret, frame = cap.read() # Read the next frame
        if not ret: # If no more frames, break the loop
            break 

        # Save the current frame as an image file
        frame_path = os.path.join(frame_dir, f"frame_{count}.jpg")
        cv2.imwrite(frame_path, frame)
        frames.append(frame_path) # Add frame path to the list
        count += 1 # Increment frame counter

    cap.release() # Release the video capture object
    print(f"[INFO] Frames extracted and saved to {frame_dir}")
    return frames, frame_dir

def extract_audio(video_path):
    # Define the output audio file path
    audio_path = f"{os.path.splitext(video_path)[0]}.wav"
    if not os.path.exists(audio_path):
        # Use FFmpeg to extract audio from the video
        os.system(f"ffmpeg -i {video_path} -q:a 0 -map a {audio_path} -y")
        print(f"[INFO] Audio extracted and saved as {audio_path}")
    else:
        print(f"[INFO] Audio already exists at {audio_path}")
    # Load the audio using librosa
    audio, sr = librosa.load(audio_path, sr=None)
    return audio, audio_path 

def delete_files(file_paths):
    # Delete files from the provided list
    for file_path in file_paths:
        if os.path.exists(file_path):
            os.remove(file_path)
            print(f"[INFO] Deleted file: {file_path}")

def delete_directory(directory_path):
    # Delete the directory and its contents
    if os.path.exists(directory_path):
        for root, dirs, files in os.walk(directory_path, topdown=False):
            for file in files:
                os.remove(os.path.join(root, file))
            for dir in dirs:
                os.rmdir(os.path.join(root, dir))
        os.rmdir(directory_path)
        print(f"[INFO] Deleted directory: {directory_path}")

def create_database(db_path):
    if not os.path.exists(db_path):
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS RetrievalDatabase (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ByteSequence TEXT NOT NULL,
                VideoID INTEGER NOT NULL,
                FeatureID TEXT NOT NULL,
                PositionID INTEGER NOT NULL
            )
        """)
        conn.commit()
        conn.close()
        print(f"[INFO] SQLite database created at {db_path}")
    else:
        print(f"[INFO] Database already exists at {db_path}")

def insert_unique_into_database(db_path, byte_sequence, video_id, feature_id, position_id):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT COUNT(*) FROM RetrievalDatabase WHERE ByteSequence = ?
    """, (byte_sequence,))
    if cursor.fetchone()[0] == 0:  # Only insert if the ByteSequence is unique
        cursor.execute("""
            INSERT INTO RetrievalDatabase (ByteSequence, VideoID, FeatureID, PositionID)
            VALUES (?, ?, ?, ?)
        """, (byte_sequence, video_id, feature_id, position_id))
        conn.commit()
    conn.close()

def check_database_integrity(db_path):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM RetrievalDatabase WHERE ByteSequence IS NULL OR ByteSequence = ''")
    null_count = cursor.fetchone()[0]
    conn.close()
    return null_count == 0
    
def calculate_sift_descriptors(frame_path):
    # Read the frame image
    frame = cv2.imread(frame_path)
    # Convert the frame to grayscale
    gray_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    # Create a SIFT object
    sift = cv2.SIFT_create()
    # Detect keypoints and compute descriptors
    keypoints, descriptors = sift.detectAndCompute(gray_frame, None)
    # Compute a hash value based on the descriptors
    if descriptors is not None:
        hash_sift = ''.join(format(int(np.sum(descriptors) % 256), '08b'))  # Convert to 8-bit binary string
    else:
        hash_sift = '00000000' # If no descriptors, set hash to 0
    return hash_sift 

def calculate_ste_hash(audio_signal, frame_length=2048):
    # Compute energy for each frame of audio
    energy = [np.sum(audio_signal[i:i + frame_length] ** 2) for i in range(0, len(audio_signal), frame_length)]
    # Generate a binary hash sequence based on energy values
    hash_ste = [format(int(e % 256), '08b') for e in energy]  
    return hash_ste 

def calculate_dwt_hash(audio_signal):
    # Perform DWT using PyWavelets and 'db1' wavelet
    coeffs = pywt.dwt(audio_signal, 'db1')
    # Coefficients from DWT are returned as a tuple: (approximation, detail)
    approximation, detail = coeffs
    # Combine the approximation and detail coefficients
    combined_coeffs = np.concatenate((approximation, detail))
    # Generate hash based on the combined coefficients
    hash_dwt = [format(int(x % 256), '08b') for x in combined_coeffs]
    return hash_dwt

def update_retrieval_database(db_path, video_id, feature_id, position_id, hash_sequence):
    byte_sequence = ''.join(map(str, hash_sequence))  # Convert hash sequence to string
    insert_unique_into_database(db_path, byte_sequence, video_id, feature_id, position_id)

def check_all_hash_sequences_generated(db_path):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(DISTINCT ByteSequence) FROM RetrievalDatabase")
    unique_count = cursor.fetchone()[0]
    conn.close()
    return unique_count == 256

def video_retrieval_database_construction(videos_dir, db_path):
    start_time = time.time() #Start Time

    create_database(db_path)

    # Load progress if it exists
    if os.path.exists(PROGRESS_FILE):
        progress = load_progress()
    else:
        progress = {"video_index": 0, "frame_index": 0, "feature_stage": "SIFT"}
    video_index = progress["video_index"]
    frame_index = progress["frame_index"]
    feature_stage = progress["feature_stage"]

    carrier_videos = []  # To track processed videos
    # List all video files in the specified directory
    video_files = [os.path.join(videos_dir, f) for f in os.listdir(videos_dir) if f.endswith(".mp4")]
    output_dir = "Processed" # Directory to store processed files
    os.makedirs(output_dir, exist_ok=True)

    def handle_interrupt(signal, frame):
        print("\n[INFO] KeyboardInterrupt detected. Saving progress ....")
        save_progress({"video_index": video_index, "frame_index": frame_index, "feature_stage": feature_stage})
        exit(1)

    signal.signal(signal.SIGINT, handle_interrupt)

    # Process each video file
    for i, video_path in enumerate(video_files):
        if check_all_hash_sequences_generated(db_path):
            print("[INFO] All 256 unique hash sequences have been generated. Terminating early.")
            break

        video_id = i + 1 # Assign a unique ID to the video

        # Step 3: Extract frame images
        frames, frame_dir = extract_frames(video_path, output_dir)

        # Time the process of hash generation based on SIFT 
        sift_start_time = time.time()

        if feature_stage == "SIFT":
            # Step 4-6: Process each frame to generate SIFT hash
            print("[INFO] Hash sequence generation from SIFT features has started")
            for j, frame_path in enumerate(frames[frame_index:], start=frame_index):  # Start from frame_index
                hash_sift = calculate_sift_descriptors(frame_path)
                update_retrieval_database(db_path, video_id, 'SIFT', j, [hash_sift]) # Wrap the single value in a list to make it iterable
                # Save progress
                save_progress({"video_index": i, "frame_index": j + 1, "feature_stage": "SIFT"})
                frame_index = j + 1 # Save frame index locally in order to save progress upon keyboard interrupt
            sift_end_time = time.time()
            print("[INFO] Hash sequence generation from SIFT features is complete")
            print(f"[INFO] SIFT hash sequence generation took {sift_end_time - sift_start_time:.2f} seconds")

            # Save progress
            save_progress({"video_index": i, "frame_index": 0, "feature_stage": "STE"})
            # Move to next stage
            feature_stage = "STE"  

        # Step 8: Extract audio
        audio, audio_path = extract_audio(video_path)

        # Time the process of hash generation based on STE 
        ste_start_time = time.time()

        
        if feature_stage == "STE":
            # Step 9-11: Short-term energy hash
            print("[INFO] Hash sequence generation from STE features has started")
            hash_ste = calculate_ste_hash(audio)
            for j, h in enumerate(hash_ste):
                update_retrieval_database(db_path, video_id, 'STE', j, [h]) # Wrap the single value in a list to make it iterable
                # Save progress
                save_progress({"video_index": i, "frame_index": j + 1, "feature_stage": "STE"})
            ste_end_time = time.time()
            print("[INFO] Hash sequence generation from STE features is complete")
            print(f"[INFO] STE hash sequence generation took {ste_end_time - ste_start_time:.2f} seconds")
            # Save progress
            save_progress({"video_index": i, "frame_index": 0, "feature_stage": "DWT"})
            # Move to next stage
            feature_stage = "DWT" 
        
        # Time the process of hash generation based on DWT coefficients
        dwt_start_time = time.time()

        if feature_stage == "DWT":
            # Step 13-15: DWT hash
            print("[INFO] Hash sequence generation from DWT features has started")
            hash_dwt = calculate_dwt_hash(audio)
            for j, h in enumerate(hash_dwt):
                update_retrieval_database(db_path, video_id, 'DWT', j, [h]) # Wrap the single value in a list to make it iterable
                # Save progress
                save_progress({"video_index": i, "frame_index": j + 1, "feature_stage": "DWT"})
            dwt_end_time = time.time()
            print("[INFO] Hash sequence generation from DWT features is complete")
            print(f"[INFO] DWT hash sequence generation took {dwt_end_time - dwt_start_time:.2f} seconds")
            # Save progress
            save_progress({"video_index": i + 1, "frame_index": 0, "feature_stage": "SIFT"})
            # Move to next video
            feature_stage = "SIFT"

        # Step 17: Append to carrier videos
        carrier_videos.append(video_path)
        print(f"[INFO] Video {video_path} processed")

    end_time = time.time()
    total_duration = end_time - start_time
    print(f"[INFO] Retrieval database construction completed in {total_duration:.2f} seconds")
    
    # Step 18-20: Check the retrieval database and finalize
    if check_database_integrity(db_path):
        print("[INFO] Retrieval database successfully constructed and verified to be non-empty.")
    else:
        print("[WARNING] Retrieval database contains empty or null entries.")

    delete_directory(frame_dir)
    delete_files([audio_path])
    
    # Step 21: Return the constructed retrieval database and carrier videos
    return db_path, carrier_videos

# Example usage
videos_dir = "Videos" # Directory containing input videos
db_path = "retrieval_database.sqlite"
db_path, carrier_videos = video_retrieval_database_construction(videos_dir, db_path)
print(f"[INFO] Database stored at {db_path}")
print(f"[INFO] Carrier Videos: {carrier_videos}")
