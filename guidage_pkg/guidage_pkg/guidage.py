import rclpy
from rclpy.node import Node

import numpy as np

from std_msgs.msg import UInt16MultiArray
from geometry_msgs.msg import Pose, PoseStamped
from enum import Enum

from .Balle import *

path_H = [[531, 151],[641, 61],[751, 151]]
path_B = [[531, 575],[641, 665],[751, 575]]
indice_suivi = 0

class Drone_State(Enum):
    start = 1
    change_zone = 2
    Go_to_ball = 3
    Go_to_safeZone = 4

def euler_from_quaternion(quaternion):
    """
    Converts quaternion (w in last place) to euler roll, pitch, yaw
    quaternion = [x, y, z, w]
    Bellow should be replaced when porting for ROS 2 Python tf_conversions is done.
    """
    x = quaternion.x
    y = quaternion.y
    z = quaternion.z
    w = quaternion.w

    sinr_cosp = 2 * (w * x + y * z)
    cosr_cosp = 1 - 2 * (x * x + y * y)
    roll = np.arctan2(sinr_cosp, cosr_cosp)

    sinp = 2 * (w * y - z * x)
    pitch = np.arcsin(sinp)

    siny_cosp = 2 * (w * z + x * y)
    cosy_cosp = 1 - 2 * (y * y + z * z)
    yaw = np.arctan2(siny_cosp, cosy_cosp)

    return roll, pitch, yaw


def nettoyer(tab_de_balles):
    nouv_tab = []
    for i in range(len(tab_de_balles)):
        if i == 0:
            nouv_tab.append(tab_de_balles[i])
        else:
            ajout = True
            for ele in nouv_tab:
                if ele == tab_de_balles[i]:
                    ajout = False
            if ajout:
                nouv_tab.append(tab_de_balles[i])
    return nouv_tab


def cost_fnct(pos_robot, zone, balle, K_d=1, K_a=4, K_z=1):
    balle_pose = balle.get_pose()
    cost_dist = ((balle_pose[0]*1.0-pos_robot[0])**2 +
                 (balle_pose[1]*1.0-pos_robot[1])**2)**0.5
    cost_age = balle.age
    cost_zone = ((pos_robot[0]*1.0-zone[0])**2 +
                 (balle_pose[1]*1.0-zone[1])**2)**0.5
    total_cos = K_d*cost_dist+K_a*cost_age + K_z*cost_zone
    return max(total_cos/100., 0.)


class Guidage(Node):

    def __init__(self):
        # Create node
        super().__init__('guidage')
        self.declare_parameter('display_mode', False)
        self.debug_mode = self.get_parameter(
            'display_mode').get_parameter_value().bool_value
        
        # Variable
        self.x, self.y, self.yaw = None, None, None
        self.target_ball = [None, None]
        self.target = [None, None]
        self.robot_state = Drone_State.start

        self.change_zone = True
        self.capture_ball = False
        self.in_safezone = False

        # Balls position subscriber
        self.subscription_balls = self.create_subscription(
            UInt16MultiArray, '/ball_positions', self.sub_balls_callback, 10)
        self.subscription_balls  # Avoid warning unused variable
        # Save balls position
        self.balles_pres = []
        self.safezones_positions_matrix = np.array([[0, 0], [0, 0]])

        # Safe zone position subscriber
        self.subscription_safezones = self.create_subscription(
            UInt16MultiArray, '/safezone_positions', self.sub_safezones_callback, 10)
        self.subscription_safezones  # Avoid warning unused variable
        # Save Safe zone position
        self.safezones_positions = np.array([])

        # Robot position subscriber
        self.subscription_robot_pos = self.create_subscription(
            PoseStamped, "robot_position", self.robot_position_callback, 10)
        self.subscription_robot_pos

        # Create ball positions publisher
        self.target_publisher = self.create_publisher(Pose, 'target', 10)
    
    def robot_position_callback(self, msg):
        self.x = msg.pose.position.x
        self.y = msg.pose.position.y
        quat = msg.pose.orientation
        roll, pitch, self.yaw = euler_from_quaternion(quat)

    def sub_balls_callback(self, array_msg):
        global target_ball
        balles = np.array(array_msg.data).reshape((-1, 2))
        balle_vue_ce_tour = [False]*len(self.balles_pres)
        for ele in balles:
            nouvelle_balle = Balle(ele[0], ele[1])
            ajout = True
            for i in range(len(self.balles_pres)):
                if self.balles_pres[i] == nouvelle_balle:
                    self.balles_pres[i].set_pose(nouvelle_balle.get_pose()[
                                                 0], nouvelle_balle.get_pose()[1])
                    balle_vue_ce_tour[i] = True
                    ajout = False
            if ajout:
                balle_vue_ce_tour.append(True)
                self.balles_pres.append(nouvelle_balle)
        for i in range(len(self.balles_pres)):
            if balle_vue_ce_tour[i]:
                self.balles_pres[i].vieillir()
                self.balles_pres[i].tour_pas_vue = 0
            else:
                self.balles_pres[i].tour_pas_vue += 1

        balle_a_garder = []
        for ele in self.balles_pres:
            if ele.tour_pas_vue > 3:
                balle_a_garder.append(False)
            else:
                balle_a_garder.append(True)
        balle_nouv = []
        for i in range(len(balle_a_garder)):
            if balle_a_garder[i]:
                balle_nouv.append(self.balles_pres[i])
                if self.debug_mode:
                    print(self.balles_pres[i])
        self.balles_pres = balle_nouv
        self.balles_pres = nettoyer(self.balles_pres)
        if self.debug_mode:
            print("en tout", len(self.balles_pres), "balles")
        ind_min, val_min = -1, 1000000000
        for ind, balle_pres in enumerate(self.balles_pres):
            if self.debug_mode:
                print(balle_pres.age)
            if balle_pres.age > 10:
                cost = min(cost_fnct((100, 100), self.safezones_positions_matrix[0], balle_pres), cost_fnct(
                    (100, 100), self.safezones_positions_matrix[1], balle_pres))
                if self.debug_mode:
                    print(cost)
                if cost < val_min:
                    val_min, ind_min = cost, ind

        if ind_min == -1:
            self.target_ball = [0, 0]
        else:
            self.target_ball = self.balles_pres[ind_min].get_pose()

        self.publish_target()

    def sub_safezones_callback(self, array_msg):
        self.safezones_positions_matrix = np.array(
            array_msg.data).reshape((-1, 2))

    def publish_target(self):
        if self.x is not None:
            # print(self.robot_state)
            # print("pos robot : ", self.x, self.y, "cible : ", self.target[0], self.target[1])
            self.action_state()
            self.update_state()

        if self.target[0] is not None:
            pose_msg = Pose()
            pose_msg.position.x = float(self.target[0])
            pose_msg.position.y = float(self.target[1])
            self.target_publisher.publish(pose_msg)

    def update_state(self):
        global indice_suivi
        if self.robot_state == Drone_State.start:
            self.robot_state = Drone_State.change_zone
            indice_suivi = 0
        elif (self.robot_state == Drone_State.change_zone and not self.change_zone):
            self.change_zone = True
            self.robot_state = Drone_State.Go_to_ball
        elif (self.robot_state == Drone_State.Go_to_ball and self.capture_ball):
            self.robot_state = Drone_State.Go_to_safeZone
        elif (self.robot_state == Drone_State.Go_to_safeZone and self.in_safezone):
            self.robot_state = Drone_State.start

    def action_state(self):
        if self.robot_state == Drone_State.start:
            if (self.x < 641 and self.target_ball[0] < 641) or (self.x > 641 and self.target_ball[0] > 641):
                self.change_zone = False
            elif (self.x > 641 and self.target_ball[0] < 641) or (self.x < 641 and self.target_ball[0] > 641):
                self.change_zone = True
            else:
                self.change_zone = True
                print("erreur cas imprévu")
        
        elif self.robot_state == Drone_State.change_zone:
            global indice_suivi
            if self.x < 641 and self.target_ball[0] > 641:
                if self.y < 360 : 
                    if(self.x > path_H[0][0] - 54):
                        if(self.y < path_H[0][1] + 54): 
                            indice_suivi = 1
                    if(self.x > path_H[1][0] - 54):
                        if(self.y < path_H[1][1]+20):
                            indice_suivi = 2
                    self.target = path_H[indice_suivi]
                else:
                    if(self.x > path_B[0][0] - 54):
                        if(self.y < path_B[0][1] + 54): 
                            indice_suivi = 1
                    if(self.x > path_B[1][0] - 54):
                        if(self.y < path_B[1][1]+20):
                            indice_suivi = 2
                    self.target = path_B[indice_suivi]
            elif self.x > 641 and self.target_ball[0] < 641:
                if self.y < 360:
                    if(self.x < path_H[2][0] + 54 and self.x > path_H[1][0]+80):
                        if(self.y < path_H[2][1] + 54): 
                            indice_suivi = 1
                    if(self.x < path_H[1][0] + 54):
                        if(self.y < path_H[1][1]+20):
                            indice_suivi = 2
                    self.target = path_H[len(path_H)-indice_suivi-1]
                else:
                    if(self.x < path_B[2][0] + 54 and self.x > path_B[1][0]+80):
                        if(self.y < path_B[2][1] + 54): 
                            indice_suivi = 1
                    if(self.x < path_B[1][0] + 54):
                        if(self.y < path_B[1][1]+20):
                            indice_suivi = 2
                    self.target = path_B[len(path_B)-indice_suivi-1]
            else:
                self.change_zone = False
        
        elif self.robot_state == Drone_State.Go_to_ball:
            self.target = self.target_ball
        


def main(args=None):
    pos_robot = (100, 100)
    # Init
    rclpy.init(args=args)

    # Create the image parser
    guidage = Guidage()

    # Loop
    rclpy.spin(guidage)

    # Kill properly the programs
    guidage.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':
    main()
