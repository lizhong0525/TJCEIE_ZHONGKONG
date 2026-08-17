import numpy as np
from scipy.spatial.transform import Rotation as R

def estimate_6d_pose(pointcloud: np.ndarray):
    """
    输入: pointcloud 是 Nx3 的 numpy 数组 (一堆3D点)
    输出: dict { "position": [x,y,z], "orientation": [roll, pitch, yaw] }
    """
    # 1. 位置估计：直接取点云的质心（抓取点）
    centroid = np.mean(pointcloud, axis=0)
    
    # 2. 姿态估计：对点云做 PCA，算出主轴方向
    # 去中心化
    centered_pts = pointcloud - centroid
    # 计算协方差矩阵
    cov = np.cov(centered_pts.T)
    # 特征值分解，最大的特征向量就是物体的"长轴"方向
    eigenvalues, eigenvectors = np.linalg.eig(cov)
    main_axis = eigenvectors[:, np.argmax(eigenvalues)]  # 主方向
    
    # 3. 把主轴方向转换成欧拉角 (roll, pitch, yaw)
    # 注意：这里默认物体的长轴作为 Z 轴方向，你可以根据实际几何体调整
    # 构造旋转矩阵 (把世界坐标系的 Z 轴 旋转到 main_axis 方向)
    z_axis = np.array([0, 0, 1])
    v = np.cross(z_axis, main_axis)
    s = np.linalg.norm(v)
    c = np.dot(z_axis, main_axis)
    if s == 0:
        rot_matrix = np.eye(3)
    else:
        vx = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
        rot_matrix = np.eye(3) + vx + np.dot(vx, vx) * ((1 - c) / (s ** 2))
    
    # 转为欧拉角 (scipy 库帮你算)
    r = R.from_matrix(rot_matrix)
    roll, pitch, yaw = r.as_euler('xyz', degrees=False)  # 注意输出弧度
    
    return {
        "position": centroid.tolist(),
        "orientation": [roll, pitch, yaw]
    }