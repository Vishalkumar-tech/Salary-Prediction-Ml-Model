
echo "===== UBUNTU VERSION ====="; lsb_release -a; echo -e "\n===== CPU ====="; nproc; lscpu | grep -E 'Model name|CPU\(s\)'; echo -e "\n===== MEMORY ====="; free -h; echo -e "\n===== DISK SPACE ====="; df -h /; echo -e "\n===== SYSTEM UPTIME ====="; uptime

sudo ss -lntup | grep -E ':(443|9200|9300|1514|1515|55000)\b' || echo "No matching ports are listening"
