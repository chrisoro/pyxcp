g++ -std=c++20 -O0  -ggdb -march=native -fexceptions -ffast-math -ftree-vectorize -msse4 -mfpmath=sse -pg -fopt-info-vec-all -Wall -Wextra -Weffc++ -fcoroutines -DLZ4_DEBUG=1 -DSTANDALONE_REKORDER=1  lz4.cpp rekorder.cpp -o rekorder.exe
