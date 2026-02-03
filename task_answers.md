Imagine we are evaluating a new storage protocol (like S3 ). You need to develop a prototype for a load testing tool 
that uses fio as the load generation engine and provides an analytical report.

The Assignment

## 1. Research Phase 
Independently research the tools fio and iperf3. In your submission, provide a brief summary of: 
Which fio parameters you would use to simulate: 
    An OLTP Database workload. 
    A streaming video service. 
What is the difference between iodepth, numjobs, and direct=1?

### Answer:

FIO Parameters for Different Workloads:

**OLTP Database.** For a database like PostgreSQL or MySQL, the workload is usually many small "reads" and "writes" happening at the same time.
I would use these fio parameters:
- rw=randrw: Databases don't read data in a straight line; they jump around (random I/O).
- bs=4k or 8k: Databases move/operate data in small blocks (4 to 8 kilobytes).
- iodepth=32: This simulates that a lot of users are sending requests to the database simultaneously at the same time.

**Video Streaming Service.**
- rw=read: Users are mostly downloading (reading) the video file.
- bs=1M: To keep the video smooth, we read much larger chunks of data at once.
- direct=1: We want to measure the disk speed directly, without the computer "cheating" by using temporary memory (cache).

#### Explaining:
 - numjobs: This is like having multiple workers. If numjobs=4, fio starts 4 separate processes doing the work. 
It is used to see how the system handles multiple tasks at once. Mostly depends on CPU perfomance.
 - iodepth: This is like how many orders could be handled at the same time. 
If iodepth=32, one worker sends 32 requests to the disk before waiting for an answer. This helps to check the disk's performance. Mostly depends on disk's controller perfomance.
 - direct=1: Normally, the Operating System tries to be faster and stores data in RAM (bufferization) to make things faster. 
Option "direct=1" tells the system: "Go straight to the hardware." This gives us the honest speed of the physical disk without using of any buffer from RAM.

Iperf3 Summary: While fio is testing my disks, iperf3 tests my network. I would use it to check if the connection between my server and the user is fast enough to support the video stream or the database traffic.


## 2. Development (Python )
Create a small application or test framework that performs the following:
Load Generation: Programmatically execute fio with specific parameters.
Data Collection: Use the --output-format=json flag in fio to capture machine-readable results.
Concurrency: Implement a way to run two different load profiles simultaneously (e.g., simulating a background backup while active reading is occurring).
Analysis: Parse the JSON output and print an aggregated report including: Average Throughput (MiB/s). P95 and P99 Latency. Total IOPS achieved.
Note on Language: While this task can be completed in Java, we highly value Python for this role as it is the primary language for our system automation. If you can complete this in Python despite your primary experience being in Java, it will be viewed very favorably as a sign of technical adaptability.

### Answer: code in current repo.

## 3. Analytical Theory 
In a text file, answer the following: If the Average Latency is low, but the 99th Percentile (P99) is extremely high, what does this tell you about the storage system? Which metrics from iperf3 would you include in your report to determine if the network is the primary bottleneck? How would you handle data aggregation for a 24-hour "Soak Test"?
### Answer:
The 99th Percentile (P99) is extremely high means that storage in heterogeneous state,
with most requests are fast (low average latency), but a small number of requests taking a very long time (high P99 latency).

I would include the following iperf3 metrics in my report to determine if the network is the primary bottleneck:
- Throughput (Bitrate): Real throughput. If it is lower than the channel width (for example, 200 Mbit/s on a Gigabit link), the network is a candidate for a bottleneck.
- Retransmits (For TCP). The most important indicator. If the number of retries is high, then packets are lost and the system has to resend them, which increases latency.
- Jitter: (For UDP). Need for measurement of fluctuations in packet delivery times. High jitter ruins the performance of Real-time systems.
- Packet Loss: Percentage of lost packets.

For a 24-hour "Soak Test", I would handle data aggregation as follows:
 - Interval aggregation - using buckets.  Instead of recording each request, I would collect statistics, 
for example, for every minute.
 - Histograms: instead of the average value, should save the distribution (how many requests fell in the range of 0-10ms, how many in 10-50ms, etc.). This will allow you to calculate percentile 99 even after a day. 
 - Rolling Windows: use moving averages to smooth graphs. Tools: specialized databases (Prometheus, InfluxDB) and visualizing in Grafana.
