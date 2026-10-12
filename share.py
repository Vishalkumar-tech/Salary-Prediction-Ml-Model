
echo "===== UBUNTU VERSION ====="; lsb_release -a; echo -e "\n===== CPU ====="; nproc; lscpu | grep -E 'Model name|CPU\(s\)'; echo -e "\n===== MEMORY ====="; free -h; echo -e "\n===== DISK SPACE ====="; df -h /; echo -e "\n===== SYSTEM UPTIME ====="; uptime
